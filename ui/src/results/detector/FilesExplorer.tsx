/**
 * Files: a tree coloured by each file's likelihood (unscored files greyed out), and the
 * selected file with its excerpt, the notes on its marked lines, the model's verdict and
 * the signals.
 */
import { type CSSProperties, Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../../components/Icon";
import { WeightBar } from "../GenericResult";
import styles from "./detector.module.css";
import {
  ancestors,
  buildTree,
  fileScore,
  probabilityColor,
  REASON_LABEL,
  SIDE_LABEL,
  type TreeFolder,
  type TreeNode,
} from "./logic";
import type { DetectorData, Excerpt, ExcerptMark, FileScore } from "./types";

export interface Selection {
  path: string;
  line?: number;
  at: number; // when it was picked, so picking the same line again scrolls again
}

function Dot({ p, byModel = true }: { p: number | null; byModel?: boolean }) {
  return (
    <span
      className={styles.dot}
      data-unscored={p === null}
      data-signals={p !== null && !byModel}
      style={p === null ? undefined : ({ "--c": probabilityColor(p) } as CSSProperties)}
    />
  );
}

function TreeRows({
  folder,
  depth,
  open,
  toggle,
  selected,
  onSelect,
}: {
  folder: TreeFolder;
  depth: number;
  open: Set<string>;
  toggle: (path: string) => void;
  selected: string | undefined;
  onSelect: (path: string) => void;
}) {
  return (
    <>
      {folder.children.map((node: TreeNode) => {
        const indent = { "--depth": depth } as CSSProperties;
        if (node.kind === "folder") {
          const isOpen = open.has(node.path);
          return (
            <Fragment key={node.path}>
              <button
                type="button"
                className={styles.treeRow}
                style={indent}
                onClick={() => toggle(node.path)}
                aria-expanded={isOpen}
              >
                <Icon name="chevronRight" size={11} className={styles.treeChevron} />
                <span className={styles.treeName}>{node.name}/</span>
              </button>
              {isOpen && (
                <TreeRows
                  folder={node}
                  depth={depth + 1}
                  open={open}
                  toggle={toggle}
                  selected={selected}
                  onSelect={onSelect}
                />
              )}
            </Fragment>
          );
        }
        const unscored = node.probability === null;
        return (
          <button
            key={node.path}
            type="button"
            className={styles.treeRow}
            style={indent}
            data-file
            data-unscored={unscored}
            aria-current={node.path === selected || undefined}
            disabled={unscored}
            title={unscored ? `Not scored: ${REASON_LABEL[node.reason ?? ""] ?? node.reason}` : node.path}
            onClick={() => onSelect(node.path)}
          >
            <Dot p={node.probability} byModel={node.byModel} />
            <span className={styles.treeName}>{node.name}</span>
            {node.hasExcerpt && <span className={styles.treeFlag} title="Has marked lines" />}
            <span className={styles.treeScore}>
              {unscored ? (REASON_LABEL[node.reason ?? ""] ?? node.reason) : node.probability?.toFixed(2)}
            </span>
          </button>
        );
      })}
    </>
  );
}

function markOf(marks: ExcerptMark[], line: number): ExcerptMark | undefined {
  // "for" wins over "against" over "context" when spans overlap
  const order = { for: 0, against: 1, context: 2 } as const;
  return marks
    .filter((m) => m.line_start <= line && line <= m.line_end)
    .sort((a, b) => order[a.side] - order[b.side])[0];
}

/** The line a mark's note stands beside: its first line that the excerpt actually shows. */
function anchorOf(excerpt: Excerpt, mark: ExcerptMark): number {
  for (const hunk of excerpt.hunks) {
    const last = hunk.start_line + hunk.lines.length - 1;
    if (mark.line_end < hunk.start_line || mark.line_start > last) continue;
    return Math.max(mark.line_start, hunk.start_line);
  }
  return mark.line_start;
}

const lineSpan = (m: ExcerptMark) =>
  m.line_start === m.line_end ? `${m.line_start}` : `${m.line_start}–${m.line_end}`;

/**
 * The excerpt, with each mark's note in the margin beside the lines it is about. Notes are
 * placed level with their first line, then pushed down just enough not to overlap, so the
 * code keeps its even line spacing. On a narrow screen they become a list under the code.
 */
function Code({ excerpt, focusLine, focusAt }: { excerpt: Excerpt; focusLine?: number; focusAt?: number }) {
  const focusRef = useRef<HTMLTableRowElement | null>(null);
  const rows = useRef(new Map<number, HTMLTableRowElement>());
  const notesRef = useRef<HTMLOListElement>(null);
  const [tops, setTops] = useState<number[]>([]);
  const notes = useMemo(
    () =>
      excerpt.marks
        .map((mark) => ({ mark, anchor: anchorOf(excerpt, mark) }))
        .sort((a, b) => a.anchor - b.anchor),
    [excerpt],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll again whenever a line is picked
  useEffect(() => {
    focusRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusLine, focusAt]);

  useLayoutEffect(() => {
    const list = notesRef.current;
    if (!list) return;
    const place = () => {
      // on a narrow screen the notes are a plain list under the code: nothing to place
      const first = list.children[0];
      if (first && getComputedStyle(first).position !== "absolute") {
        list.style.minHeight = "";
        return;
      }
      const origin = list.getBoundingClientRect().top;
      let floor = 0;
      const next = notes.map(({ anchor }, i) => {
        const row = rows.current.get(anchor);
        const want = row ? row.getBoundingClientRect().top - origin : floor;
        const top = Math.max(want, floor);
        floor = top + ((list.children[i] as HTMLElement | undefined)?.offsetHeight ?? 0) + 8;
        return Math.round(top);
      });
      list.style.minHeight = `${Math.round(floor)}px`;
      setTops((prev) => (prev.length === next.length && prev.every((t, i) => t === next[i]) ? prev : next));
    };
    place();
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(place);
    watch.observe(list);
    return () => watch.disconnect();
  }, [notes]);

  return (
    <div className={styles.code}>
      <div className={styles.codeScroll}>
        <table>
          <tbody>
            {excerpt.hunks.map((hunk, h) => {
              const previousEnd =
                h > 0
                  ? (excerpt.hunks[h - 1]?.start_line ?? 0) + (excerpt.hunks[h - 1]?.lines.length ?? 0)
                  : 1;
              const gap = hunk.start_line - previousEnd;
              return (
                <Fragment key={hunk.start_line}>
                  {gap > 0 && (
                    <tr className={styles.gap}>
                      <td colSpan={2}>
                        {h === 0 ? `lines 1–${hunk.start_line - 1}` : `${gap} line${gap === 1 ? "" : "s"}`}{" "}
                        not shown
                      </td>
                    </tr>
                  )}
                  {hunk.lines.map((text, i) => {
                    const line = hunk.start_line + i;
                    const mark = markOf(excerpt.marks, line);
                    return (
                      <tr
                        key={line}
                        ref={(el) => {
                          if (el) rows.current.set(line, el);
                          else rows.current.delete(line);
                          if (line === focusLine) focusRef.current = el;
                        }}
                        data-side={mark?.side}
                        data-focus={line === focusLine || undefined}
                      >
                        <td className={styles.lineNo}>{line}</td>
                        <td className={styles.lineText}>{text || " "}</td>
                      </tr>
                    );
                  })}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {notes.length > 0 && (
        <ol ref={notesRef} className={styles.notes} aria-label="Notes on the marked lines">
          {notes.map(({ mark }, i) => (
            <li
              key={`${mark.source}-${mark.line_start}-${mark.note}`}
              className={styles.note}
              data-side={mark.side}
              style={{ top: tops[i] ?? 0 }}
            >
              <span className={styles.noteHead}>
                <b>{SIDE_LABEL[mark.side]}</b>
                <span>
                  {mark.source === "judge" ? "model" : mark.source.replaceAll("_", " ")} · line{" "}
                  {lineSpan(mark)}
                </span>
              </span>
              <span className={styles.noteText}>{mark.note}</span>
            </li>
          ))}
        </ol>
      )}
      {excerpt.truncated && (
        <p className={styles.truncated}>Some marked lines were left out to keep the report small.</p>
      )}
    </div>
  );
}

function FileView({
  file,
  excerpt,
  selection,
}: {
  file: FileScore;
  excerpt?: Excerpt;
  selection: Selection | null;
}) {
  const focusLine = selection?.path === file.path ? selection.line : undefined;
  const score = fileScore(file);
  return (
    <article className={styles.fileView}>
      <header className={styles.fileHead}>
        <div className={styles.filePath}>
          <code>{file.path}</code>
          <span className={styles.fileMeta}>
            {file.language ?? "unknown language"} · {file.lines} lines of code
            {file.is_test ? " · test file" : ""}
          </span>
        </div>
        <span className={styles.fileScores}>
          <span
            className={styles.fileScore}
            style={{ "--c": probabilityColor(score.value) } as CSSProperties}
          >
            {score.value.toFixed(2)}
          </span>
          <span className={styles.fileMeta}>{file.judge ? "the model's verdict" : "signals only"}</span>
          {file.judge && <span className={styles.fileMeta}>signals {file.probability.toFixed(2)}</span>}
        </span>
      </header>

      {file.ai_commit_touches > 0 && (
        <p className={styles.touch}>
          Changed by {file.ai_commit_touches} commit{file.ai_commit_touches === 1 ? "" : "s"} whose metadata
          names an AI tool.
        </p>
      )}

      {file.judge && (
        <div className={styles.verdict}>
          <div>
            <p className={styles.verdictLabel}>The model read this file</p>
            <p className={styles.verdictLine}>
              Likelihood {file.judge.likelihood_ai.toFixed(2)}
              <span> · its confidence {file.judge.confidence.toFixed(2)}</span>
            </p>
          </div>
          {file.judge.uncertainty_notes && (
            <p className={styles.uncertainty}>“{file.judge.uncertainty_notes}”</p>
          )}
        </div>
      )}

      {excerpt ? (
        <Code excerpt={excerpt} focusLine={focusLine} focusAt={selection?.at} />
      ) : (
        <p className={styles.noExcerpt}>
          No code excerpt: the model did not read this file, and no signal pointed at specific lines.
        </p>
      )}

      {file.signals.length > 0 && (
        <div className={styles.signals}>
          <p className={styles.signalsLabel}>Signals that fired (+ reads AI-like, − reads human-like)</p>
          <ul>
            {file.signals.map((s) => (
              <li key={`${s.signal_id}-${s.explanation}`}>
                <span className={styles.signalId}>{s.signal_id.replaceAll("_", " ")}</span>
                <span className={styles.signalText}>{s.explanation}</span>
                <WeightBar weight={s.strength} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

export function FilesExplorer({
  data,
  selection,
  onSelect,
}: {
  data: DetectorData;
  selection: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  const [query, setQuery] = useState("");
  const [showUnscored, setShowUnscored] = useState(false);
  const [order, setOrder] = useState<"tree" | "score">("tree");
  const excerpts = useMemo(() => new Map(data.excerpts.map((e) => [e.path, e])), [data]);
  const files = useMemo(() => new Map(data.files.map((f) => [f.path, f])), [data]);
  const tree = useMemo(
    () => buildTree(data, { includeUnscored: showUnscored, query }),
    [data, showUnscored, query],
  );

  // start on the most likely file that has marked code, else the most likely file
  const initial =
    [...data.files]
      .filter((f) => excerpts.has(f.path) && !f.is_test)
      .sort(
        (a, b) =>
          Number(Boolean(b.judge)) - Number(Boolean(a.judge)) || fileScore(b).value - fileScore(a).value,
      )[0] ?? data.files[0];
  const current = selection?.path ?? initial?.path;
  const [open, setOpen] = useState<Set<string>>(() => {
    const start = new Set<string>();
    for (const child of tree.children) if (child.kind === "folder") start.add(child.path);
    for (const a of ancestors(current ?? "")) start.add(a);
    return start;
  });

  useEffect(() => {
    if (!selection) return;
    setOpen((o) => new Set([...o, ...ancestors(selection.path)]));
  }, [selection]);

  const toggle = (path: string) =>
    setOpen((o) => {
      const next = new Set(o);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  const select = (path: string) => onSelect({ path, at: Date.now() });
  const file = current ? files.get(current) : undefined;
  const ranked = useMemo(
    () =>
      data.files
        .filter((f) => !query || f.path.toLowerCase().includes(query.toLowerCase()))
        .sort((a, b) => fileScore(b).value - fileScore(a).value),
    [data, query],
  );

  if (!data.files.length) {
    return <p className="muted">No file could be scored.</p>;
  }

  return (
    <div className={styles.explorer}>
      <div className={styles.treePane}>
        <div className={styles.treeTools}>
          <label className={styles.search}>
            <Icon name="search" size={14} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter files"
              spellCheck={false}
            />
          </label>
          <div className={styles.toggles}>
            <button type="button" aria-pressed={order === "tree"} onClick={() => setOrder("tree")}>
              Folders
            </button>
            <button type="button" aria-pressed={order === "score"} onClick={() => setOrder("score")}>
              By score
            </button>
            {order === "tree" && (
              <button
                type="button"
                className={styles.unscoredToggle}
                aria-pressed={showUnscored}
                onClick={() => setShowUnscored(!showUnscored)}
              >
                Unscored
              </button>
            )}
          </div>
        </div>
        <div className={styles.tree}>
          {order === "tree" ? (
            <TreeRows
              folder={tree}
              depth={0}
              open={query ? new Set(allFolders(tree)) : open}
              toggle={toggle}
              selected={current}
              onSelect={select}
            />
          ) : (
            ranked.map((f) => (
              <button
                key={f.path}
                type="button"
                className={styles.treeRow}
                data-file
                aria-current={f.path === current || undefined}
                onClick={() => select(f.path)}
                style={{ "--depth": 0 } as CSSProperties}
              >
                <Dot p={fileScore(f).value} byModel={fileScore(f).byModel} />
                <span className={styles.treeName} title={f.path}>
                  {f.path}
                </span>
                {excerpts.has(f.path) && <span className={styles.treeFlag} title="Has marked lines" />}
                <span className={styles.treeScore}>{fileScore(f).value.toFixed(2)}</span>
              </button>
            ))
          )}
        </div>
        <p className={styles.legend}>
          <span>
            <Dot p={0} /> human-like
          </span>
          <span>
            <Dot p={1} /> AI-like
          </span>
          <span>
            <Dot p={0.5} byModel={false} /> signals only
          </span>
          <span>
            <Dot p={null} /> not scored
          </span>
          <span>
            <span className={styles.treeFlag} /> marked lines
          </span>
        </p>
      </div>
      {file ? (
        <FileView file={file} excerpt={excerpts.get(file.path)} selection={selection} />
      ) : (
        <p className="muted">Pick a file.</p>
      )}
    </div>
  );
}

function allFolders(folder: TreeFolder): string[] {
  return folder.children.flatMap((c) => (c.kind === "folder" ? [c.path, ...allFolders(c)] : []));
}
