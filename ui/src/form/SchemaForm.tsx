import { type FormEvent, useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { type AgentInfo, ApiError, api, call } from "../api/client";
import { Block } from "../components/Block";
import { Button } from "../components/Button";
import { CopyButton } from "../components/CopyButton";
import { Icon } from "../components/Icon";
import { FieldInput } from "./Fields";
import { ModelChoice, type RunModel } from "./ModelChoice";
import styles from "./SchemaForm.module.css";
import {
  buildPayload,
  cliCommand,
  type FormValue,
  type FormValues,
  fieldsFromSchema,
  initialValues,
} from "./schema";

export async function startRun(
  agentId: string,
  payload: Record<string, unknown>,
  llm?: RunModel | null,
): Promise<string> {
  const query = llm ? { provider: llm.provider, model: llm.model || undefined } : undefined;
  const created = await call(
    api.POST("/agents/{agent_id}/runs", {
      params: { path: { agent_id: agentId }, query },
      body: payload,
    }),
  );
  return created.run_id;
}

/** The input form for any agent, generated from its JSON schema. */
export function SchemaForm({
  agent,
  initial,
  disabledReason,
}: {
  agent: AgentInfo;
  initial?: FormValues;
  disabledReason?: string;
}) {
  const navigate = useNavigate();
  const fields = useMemo(() => fieldsFromSchema(agent.input_schema, agent.primary_input), [agent]);
  const [values, setValues] = useState<FormValues>(() => ({ ...initialValues(fields), ...initial }));
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string>();
  const [runModel, setRunModel] = useState<RunModel | null>(null);
  const chooseModel = useCallback((m: RunModel | null) => setRunModel(m), []);

  const { payload, errors } = buildPayload(fields, values);
  const shownErrors = touched ? errors : {};
  const main = fields.filter((f) => f.primary || f.required);
  const extra = fields.filter((f) => !f.primary && !f.required);
  const changedExtra = extra.filter((f) => f.name in payload).length;
  const command = cliCommand(agent.id, fields, payload, runModel);

  const set = (name: string) => (value: FormValue) => {
    setValues((v) => ({ ...v, [name]: value }));
    setServerError(undefined);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (disabledReason) return;
    setTouched(true);
    if (Object.keys(errors).length) return;
    setSubmitting(true);
    setServerError(undefined);
    try {
      const runId = await startRun(agent.id, payload, runModel);
      navigate(`/runs/${runId}`, { viewTransition: true });
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : (err as Error).message);
      setSubmitting(false);
    }
  };

  const reset = () => {
    setValues(initialValues(fields));
    setTouched(false);
    setServerError(undefined);
  };

  return (
    <form onSubmit={submit} noValidate>
      {main.length > 0 && (
        <Block label="Input">
          <div className={styles.fields}>
            {main.map((field, i) => (
              <FieldInput
                key={field.name}
                field={field}
                value={values[field.name] ?? null}
                error={shownErrors[field.name]}
                onChange={set(field.name)}
                autoFocus={i === 0}
              />
            ))}
          </div>
        </Block>
      )}

      {extra.length > 0 && (
        <Block
          label="Options"
          count={extra.length}
          note={changedExtra ? `${changedExtra} changed` : "All at their defaults"}
        >
          <details className={styles.more} open={changedExtra > 0 || undefined}>
            <summary className={styles.summary}>
              <Icon name="chevronRight" size={14} className={styles.chevron} />
              <span>More options</span>
            </summary>
            <div className={`${styles.fields} ${styles.extra}`}>
              {extra.map((field) => (
                <FieldInput
                  key={field.name}
                  field={field}
                  value={values[field.name] ?? null}
                  error={shownErrors[field.name]}
                  onChange={set(field.name)}
                />
              ))}
            </div>
          </details>
        </Block>
      )}

      {agent.uses_llm && (
        <Block label="Model">
          <ModelChoice value={runModel} onChange={chooseModel} />
        </Block>
      )}

      <Block>
        {serverError && (
          <p className={styles.error} role="alert">
            <Icon name="error" size={16} />
            <span>{serverError}</span>
          </p>
        )}
        <div className={styles.actions}>
          <Button
            type="submit"
            size="l"
            icon={submitting ? "spinner" : "play"}
            disabled={submitting || Boolean(disabledReason)}
            title={disabledReason}
          >
            {submitting ? "Starting" : "Run"}
          </Button>
          <Button variant="text" onClick={reset} disabled={submitting}>
            Reset
          </Button>
        </div>
      </Block>

      <Block label="Command line" note="The same run, from a terminal">
        <div className={styles.cli}>
          <code className={styles.cliCode}>{command}</code>
          <CopyButton text={command} label="Copy command" />
        </div>
      </Block>
    </form>
  );
}
