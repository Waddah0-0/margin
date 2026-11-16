/**
 * The Commit Graph's own result view: the chapters, what the history shows that a plain
 * graph doesn't, and the tree itself, with notes hanging in the margin beside the commits
 * they are about. The tree can be replayed from the first commit, and a file or a finding
 * can be lit up on it. Falls back to the generic viewer when the data isn't the agent's.
 */
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Block } from "../../components/Block";
import { Button } from "../../components/Button";
import {
  ExportButtons,
  GenericResult,
  ResultFooter,
  ResultLayout,
  Section,
  StatusBanner,
} from "../GenericResult";
import type { ResultViewProps } from "../registry";
import styles from "./history.module.css";
import {
  CHAPTER_ROW,
  commitsHighlight,
  day,
  days,
  fileHighlight,
  type Geometry,
  geometry,
  type Highlight,
  laneX,
  lifeSentence,
  plural,
  ROW,
  togetherHighlight,
  toolHighlight,
  treePath,
} from "./logic";
import { asHistoryData, type Chapter, type Commit, type HistoryData } from "./types";

const REPLAY_MS = 12_000;

function Summary({ parts, onCommit }: { parts: Chapter["summary"]; onCommit: (hash: string) => void }) {
  return (
    <>
      {parts.map((part, i) =>
        part.commit ? (
          <button
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
            key={i}
            type="button"
            className={styles.cite}
            onClick={() => onCommit(part.commit as string)}
            title="Show this commit on the tree"
          >
            {part.text}
          </button>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

function Chapters({
  data,
  onCommit,
  onChapter,
}: {
  data: HistoryData;
  onCommit: (hash: string) => void;
  onChapter: (chapter: Chapter) => void;
}) {
  const byModel = data.chapters.some((c) => c.written_by === "model");
  return (
    <Section
      title="Chapters"
      count={data.chapters.length}
      note={byModel ? "Written by the model from the commit messages" : "Written from a template"}
    >
      <ol className={styles.chapters}>
        {data.chapters.map((chapter) => (
          <li key={chapter.index} className={styles.chapter}>
            <span className={styles.chapterNo}>{String(chapter.index).padStart(2, "0")}</span>
            <div>
              <h3 className={styles.chapterTitle}>
                <button
                  type="button"
                  onClick={() => onChapter(chapter)}
                  title="Go to this chapter on the tree"
                >
                  {chapter.title}
                </button>
              </h3>
              <p className={styles.prose}>
                <Summary parts={chapter.summary} onCommit={onCommit} />
              </p>
              <p className={styles.chapterMeta}>
                {days(chapter.start, chapter.end)} · {plural(chapter.commits, "commit")}
                {chapter.areas.length > 0 && ` · ${chapter.areas.map((a) => a.path).join(", ")}`}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </Section>
  );
}

interface Item {
  key: string;
  what: ReactNode;
  detail: string;
  show: () => Highlight;
}

function Group({
  title,
  why,
  items,
  onShow,
}: {
  title: string;
  why: string;
  items: Item[];
  onShow: (highlight: Highlight) => void;
}) {
  if (!items.length) return null;
  return (
    <div className={styles.group}>
      <h3 className={styles.groupTitle}>{title}</h3>
      <p className={styles.groupWhy}>{why}</p>
      <ul className={styles.items}>
        {items.map((item) => (
          <li key={item.key}>
            <button
              type="button"
              className={styles.item}
              onClick={() => onShow(item.show())}
              title="Show on the tree"
            >
              <code className={styles.itemWhat}>{item.what}</code>
              <span className={styles.itemDetail}>{item.detail}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Findings({ data, onShow }: { data: HistoryData; onShow: (highlight: Highlight) => void }) {
  const file = (path: string, fallback: string[]) => () => {
    const life = data.files.find((f) => f.path === path);
    return life ? fileHighlight(life) : commitsHighlight(data, path, fallback, "changed");
  };
  const total =
    data.hotspots.length +
    data.couplings.length +
    data.fix_chains.length +
    data.one_person_areas.length +
    data.ai_marks.length;
  if (!total) return null;
  return (
    <Section title="What it shows" note="Counted from the history. Pick one to see it on the tree.">
      <div className={styles.groups}>
        <Group
          title="Files that change the most"
          why="Large code files that keep changing are where bugs tend to be."
          onShow={onShow}
          items={data.hotspots.map((h) => ({
            key: h.path,
            what: h.path,
            detail: `${plural(h.touches, "commit")}${h.lines ? `, ${plural(h.lines, "line")} long` : ""}`,
            show: file(h.path, h.commits),
          }))}
        />
        <Group
          title="Files that change together"
          why="In different folders, but nearly always in the same commit. A change to one probably needs the other."
          onShow={onShow}
          items={data.couplings.map((c) => ({
            key: `${c.a}+${c.b}`,
            what: (
              <>
                {c.a}
                <br />
                {c.b}
              </>
            ),
            detail: `Together in ${c.together} of the ${c.a_touches + c.b_touches - c.together} commits that changed either`,
            show: () => togetherHighlight(data, c.a, c.b, c.commits),
          }))}
        />
        <Group
          title="Runs of quick fixes"
          why="A commit followed within the hour by fix after fix to the same files."
          onShow={onShow}
          items={data.fix_chains.map((chain) => ({
            key: chain.commits.join(),
            what: (chain.commits[0] ?? "").slice(0, 7),
            detail: `${chain.commits.length - 1} fixes within ${plural(chain.minutes, "minute")}${
              chain.files.length ? `, in ${chain.files.join(", ")}` : ""
            }`,
            show: () => commitsHighlight(data, "A run of quick fixes", chain.commits, "fix"),
          }))}
        />
        {data.one_person_areas.length > 0 && (
          <div className={styles.group}>
            <h3 className={styles.groupTitle}>Areas with one author</h3>
            <p className={styles.groupWhy}>
              Nearly every change here was made by the same person. Nobody else has worked on these parts.
            </p>
            <ul className={styles.items}>
              {data.one_person_areas.map((area) => (
                <li key={area.path} className={styles.plainItem}>
                  <code className={styles.itemWhat}>{area.path}</code>
                  <span className={styles.itemDetail}>
                    One person made {Math.round(area.share * 100)}% of {area.touches} file changes
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <Group
          title="AI tool marks"
          why="Commits whose message says an AI tool took part. Reported as found, never scored: a mark does not say how much the tool wrote."
          onShow={onShow}
          items={data.ai_marks.map((mark) => ({
            key: mark.tool,
            what: mark.tool,
            detail: `${plural(mark.commits, "commit")}, first on ${day(mark.first_seen)}`,
            show: () => toolHighlight(data, mark.tool),
          }))}
        />
      </div>
    </Section>
  );
}

function CommitDetail({ commit, onClose }: { commit: Commit; onClose: () => void }) {
  const more = commit.files_changed - commit.files.length;
  return (
    <div className={styles.detail}>
      <div className={styles.detailHead}>
        <p className={styles.detailSubject}>{commit.subject}</p>
        <Button variant="text" size="s" icon="close" onClick={onClose} aria-label="Close the commit">
          Close
        </Button>
      </div>
      <p className={styles.detailMeta}>
        <code>{commit.short}</code> · {commit.author} · {day(commit.date)}
        {commit.parents.length > 1 && " · a merge"}
      </p>
      {commit.notes.length > 0 && (
        <ul className={styles.detailNotes}>
          {commit.notes.map((note) => (
            <li key={note.text} data-flagged={note.flagged || undefined}>
              {note.text}
            </li>
          ))}
        </ul>
      )}
      {commit.files.length > 0 && (
        <p className={styles.detailFiles}>
          {commit.files.map((path) => (
            <code key={path}>{path}</code>
          ))}
          {more > 0 && <span>and {more} more</span>}
        </p>
      )}
    </div>
  );
}

function Tree({
  data,
  geo,
  upTo,
  selected,
  highlight,
  onSelect,
}: {
  data: HistoryData;
  geo: Geometry;
  upTo: number;
  selected: string | null;
  highlight: Highlight | null;
  onSelect: (commit: Commit) => void;
}) {
  const path = useMemo(() => treePath(data, geo, upTo), [data, geo, upTo]);
  const chapters = new Map(data.chapters.map((c) => [c.index, c]));
  return (
    <div className={styles.rows} style={{ height: geo.height }}>
      <svg
        className={styles.lines}
        width={geo.lanesWidth}
        height={geo.height}
        viewBox={`0 0 ${geo.lanesWidth} ${geo.height}`}
        aria-hidden="true"
      >
        <path d={path} />
        {data.commits.map((commit, row) =>
          row < upTo ? null : (
            <circle
              key={commit.hash}
              cx={laneX(commit.lane)}
              cy={(geo.top[row] ?? 0) + ROW / 2}
              r={commit.hash === selected || highlight?.rows.has(row) ? 5 : 3.5}
              data-merge={commit.parents.length > 1 || undefined}
              data-flagged={commit.notes.some((n) => n.flagged) || undefined}
              data-lit={highlight?.rows.has(row) || undefined}
            />
          ),
        )}
      </svg>
      {[...geo.chapterTop].map(([index, top]) => {
        const chapter = chapters.get(index);
        if (!chapter) return null;
        return (
          <div
            key={`chapter-${index}`}
            className={styles.chapterRow}
            style={{ top, height: CHAPTER_ROW, paddingLeft: geo.lanesWidth + 8 }}
            data-hidden={chapter.last_row < upTo || undefined}
            data-chapter={index}
          >
            <span className={styles.hang}>Chapter {index}</span>
            <span className={styles.chapterRowTitle}>{chapter.title}</span>
            <span className={styles.chapterRowDates}>{days(chapter.start, chapter.end)}</span>
          </div>
        );
      })}
      {data.commits.map((commit, row) => {
        const lit = highlight?.rows.get(row);
        const flagged = commit.notes.some((n) => n.flagged);
        const notes = commit.notes.filter((n) => n.kind !== "ai");
        return (
          <button
            key={commit.hash}
            type="button"
            className={styles.row}
            style={{ top: geo.top[row], height: ROW, paddingLeft: geo.lanesWidth + 8 }}
            data-row={row}
            data-selected={commit.hash === selected || undefined}
            data-hidden={row < upTo || undefined}
            data-dim={(highlight && lit === undefined) || undefined}
            aria-pressed={commit.hash === selected}
            onClick={() => onSelect(commit)}
          >
            {(lit || notes.length > 0) && (
              <span
                className={styles.hang}
                data-flagged={(!lit && flagged) || undefined}
                data-lit={!!lit || undefined}
              >
                {lit ?? notes.map((n) => n.text).join(" · ")}
              </span>
            )}
            <span className={styles.subject}>{commit.subject}</span>
            {commit.tags.map((tag) => (
              <span key={tag} className={`tag ${styles.ref}`} data-tone="ink">
                {tag}
              </span>
            ))}
            {commit.ai_tools.map((tool) => (
              <span key={tool} className={`tag ${styles.ref}`}>
                {tool}
              </span>
            ))}
            <span className={styles.meta}>
              <code>{commit.short}</code>
              <span className={styles.date}>{day(commit.date)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function HistoryView({ run, result, data }: ResultViewProps & { data: HistoryData }) {
  const count = data.commits.length;
  const geo = useMemo(() => geometry(data), [data]);
  const treeRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  /** The newest row drawn. 0 is the whole history; `count - 1` is only the first commit. */
  const [upTo, setUpTo] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [filePath, setFilePath] = useState("");

  const scrollToRow = (row: number, block: ScrollLogicalPosition = "center") => {
    treeRef.current?.querySelector(`[data-row="${row}"]`)?.scrollIntoView?.({ behavior: "smooth", block });
  };

  useEffect(() => {
    if (!playing) return;
    const step = Math.max(1, Math.ceil(count / 600));
    const timer = window.setInterval(
      () => {
        setUpTo((current) => {
          const next = Math.max(0, current - step);
          if (next === 0) setPlaying(false);
          treeRef.current
            ?.querySelector(`[data-row="${next}"]`)
            ?.scrollIntoView?.({ behavior: "auto", block: "center" });
          return next;
        });
      },
      Math.min(250, Math.max(16, (REPLAY_MS / count) * step)),
    );
    return () => window.clearInterval(timer);
  }, [playing, count]);

  const play = () => {
    if (playing) return setPlaying(false);
    if (upTo === 0) setUpTo(count - 1);
    setPlaying(true);
  };

  const showCommit = (hash: string) => {
    const row = data.commits.findIndex((c) => c.hash === hash);
    if (row < 0) return;
    setSelected(hash);
    if (row < upTo) setUpTo(0);
    scrollToRow(row);
  };

  const show = (next: Highlight) => {
    setHighlight(next);
    setUpTo(0);
    setPlaying(false);
    const newest = Math.min(...next.rows.keys());
    if (Number.isFinite(newest)) scrollToRow(newest);
    else treeRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };

  const followFile = (path: string) => {
    setFilePath(path);
    const life = data.files.find((f) => f.path === path);
    if (life) show(fileHighlight(life));
  };

  const repo = data.repo;
  const head = data.commits[upTo];
  const followed = highlight ? data.files.find((f) => f.path === highlight.label) : undefined;
  const picked = selected ? data.commits.find((c) => c.hash === selected) : undefined;

  return (
    <ResultLayout>
      <StatusBanner result={result} />
      <Block
        label="History"
        note={
          <>
            {repo.branch && <span className={styles.branch}>{repo.branch}</span>}
            {repo.renames_followed === "exact" && (
              <span>Renames followed only when the file did not change</span>
            )}
          </>
        }
      >
        <p className={styles.lead}>{repo.name}</p>
        <p className={styles.sub}>
          {repo.truncated
            ? `The newest ${repo.shown} of ${repo.total_commits} commits`
            : plural(repo.shown, "commit")}
          {repo.first_date && repo.last_date && `, ${days(repo.first_date, repo.last_date)}`}
          {repo.authors > 0 && `, by ${plural(repo.authors, "person").replace("persons", "people")}`}
        </p>
        <ExportButtons run={run} result={result} />
      </Block>

      {count > 0 && (
        <Chapters
          data={data}
          onCommit={showCommit}
          onChapter={(chapter) => {
            setUpTo(0);
            scrollToRow(chapter.first_row, "start");
          }}
        />
      )}
      <Findings data={data} onShow={show} />

      {count > 0 && (
        <div ref={treeRef} className={styles.anchor}>
          <Block label="Tree" count={count} note="Newest first. Pick a commit to read it.">
            {data.files.length > 0 && (
              <label className={styles.follow}>
                <span>Follow a file</span>
                <input
                  className={styles.followInput}
                  list="history-files"
                  value={filePath}
                  placeholder="Type a path"
                  onChange={(e) => followFile(e.target.value)}
                />
                <datalist id="history-files">
                  {[...new Set(data.files.map((f) => f.path))].map((path) => (
                    <option key={path} value={path} />
                  ))}
                </datalist>
              </label>
            )}
          </Block>
          <div className={`m-grid ${styles.tree}`}>
            <div />
            <div className={styles.column}>
              <div className={styles.bar}>
                <div className={styles.replay}>
                  <Button variant="outlined" size="s" icon={playing ? undefined : "play"} onClick={play}>
                    {playing ? "Pause" : upTo === 0 ? "Replay" : "Play"}
                  </Button>
                  <input
                    type="range"
                    className={styles.slider}
                    min={0}
                    max={count - 1}
                    value={count - 1 - upTo}
                    aria-label="Replay the history"
                    onChange={(e) => {
                      const next = count - 1 - Number(e.target.value);
                      setPlaying(false);
                      setUpTo(next);
                      treeRef.current
                        ?.querySelector(`[data-row="${next}"]`)
                        ?.scrollIntoView?.({ behavior: "auto", block: "center" });
                    }}
                  />
                  <span className={styles.replayAt}>
                    {upTo === 0 ? "The whole history" : `Up to ${day(head?.date)} · chapter ${head?.chapter}`}
                  </span>
                </div>
                {highlight && (
                  <p className={styles.lit}>
                    <span>
                      <code>{highlight.label}</code>
                      {followed
                        ? `: ${lifeSentence(followed, data.commits)}`
                        : `: ${plural(highlight.rows.size, "commit")}`}
                    </span>
                    <Button
                      variant="text"
                      size="s"
                      icon="close"
                      onClick={() => {
                        setHighlight(null);
                        setFilePath("");
                      }}
                    >
                      Clear
                    </Button>
                  </p>
                )}
                {picked && <CommitDetail commit={picked} onClose={() => setSelected(null)} />}
              </div>
              <Tree
                data={data}
                geo={geo}
                upTo={upTo}
                selected={selected}
                highlight={highlight}
                onSelect={(commit) => setSelected(commit.hash === selected ? null : commit.hash)}
              />
            </div>
          </div>
        </div>
      )}

      <ResultFooter result={result} />
    </ResultLayout>
  );
}

export function HistoryResult(props: ResultViewProps) {
  const data = props.result.status === "error" ? null : asHistoryData(props.result.data);
  if (!data) return <GenericResult {...props} />;
  return <HistoryView {...props} data={data} />;
}
