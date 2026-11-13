/**
 * The AI Code Detector's intro on its agent page: what it reads, how it weighs the
 * evidence, and why the answer is a range. Beside the steps is a specimen of what a result
 * looks like: a few lines of code, two of them marked, each with its note in the margin.
 */
import { Block } from "../../components/Block";
import { Icon } from "../../components/Icon";
import styles from "./intro.module.css";

const METHODOLOGY = "https://github.com/Waddah0-0/margin/blob/main/docs/methodology.md";

const SPECIMEN: { no: number; text: string; side?: "for" | "against" }[] = [
  { no: 41, text: "def total(items):" },
  { no: 42, text: "    # add up the prices", side: "for" },
  { no: 43, text: "    result = 0" },
  { no: 44, text: "    for item in items:" },
  { no: 45, text: "        result += item.price * 1.0825", side: "against" },
  { no: 46, text: "    return result" },
];

export function DetectorIntro() {
  return (
    <Block label="How it reads code" note="It estimates; it never proves">
      <div className={styles.intro}>
        <ol className={styles.steps}>
          <li>
            <b>A local model reads a sample of files</b> and points at lines that suggest AI or a person. The
            quotes come from the file itself, never from the model.
          </li>
          <li>
            <b>Every Python, JavaScript and TypeScript file is checked</b> for habits such as comments that
            restate the code or leftover debugging.
          </li>
          <li>
            <b>The answer is a range, not a verdict</b>, with a confidence level and the reasons for it.
            Evidence for and against is shown side by side.
          </li>
        </ol>

        <figure className={styles.specimen} aria-hidden="true">
          <div className={styles.sheet}>
            <div className={styles.lines}>
              {SPECIMEN.map((line) => (
                <div key={line.no} className={styles.line} data-side={line.side}>
                  <span>{line.no}</span>
                  <code>{line.text}</code>
                </div>
              ))}
            </div>
            <div className={styles.notes}>
              <p data-side="for" style={{ gridRow: 2 }}>
                <b>+0.42</b> comment restates the code
              </p>
              <p data-side="against" style={{ gridRow: 5 }}>
                <b>−0.18</b> hand-tuned constant
              </p>
            </div>
          </div>
          <figcaption>What a result looks like: marked lines, and the reason beside each.</figcaption>
        </figure>
      </div>

      <p className={styles.caveat}>
        Use it to start a conversation, not to accuse anyone.{" "}
        <a className="link" href={METHODOLOGY} target="_blank" rel="noreferrer">
          How it scores, and how well it did in testing
          <Icon name="open" size={12} />
        </a>
      </p>
    </Block>
  );
}
