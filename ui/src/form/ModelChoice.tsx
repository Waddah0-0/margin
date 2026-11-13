/**
 * Which model a run uses, shown on the form of agents that use one: the default from
 * settings, or a different provider and model for this run only.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useLoad } from "../api/hooks";
import { fetchLLMSettings, PROVIDER_NAME, type ProviderId } from "../api/settings";
import { Icon } from "../components/Icon";
import { PlainTextField } from "./Fields";
import styles from "./ModelChoice.module.css";

export interface RunModel {
  provider: ProviderId;
  model: string;
}

/** `value` is null while the run uses the settings' default. */
export function ModelChoice({
  value,
  onChange,
}: {
  value: RunModel | null;
  onChange: (v: RunModel | null) => void;
}) {
  const settings = useLoad(fetchLLMSettings);
  const [open, setOpen] = useState(false);
  const data = settings.data;

  useEffect(() => {
    if (!open) onChange(null);
  }, [open, onChange]);

  if (!data) {
    return (
      <p className={styles.line}>
        <span className="muted">{settings.error ? "Model settings unavailable." : "Loading model…"}</span>
      </p>
    );
  }

  const defaults = data.providers.find((p) => p.id === data.provider);
  const chosen = value ?? { provider: data.provider, model: defaults?.model ?? "" };
  const provider = data.providers.find((p) => p.id === chosen.provider);

  return (
    <div className={styles.box} data-open={open}>
      <p className={styles.line}>
        <Icon name={provider?.on_device ? "device" : "cloud"} size={16} />
        <span className={styles.summary}>
          {value ? "This run uses" : "Runs with"} <b>{PROVIDER_NAME[chosen.provider]}</b>{" "}
          <code>{chosen.model || provider?.default_model}</code>
        </span>
        <button type="button" className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Use the default" : "Change for this run"}
        </button>
        <Link to="/settings" className="link" viewTransition>
          Model settings
        </Link>
      </p>

      {open && (
        <div className={styles.editor}>
          <fieldset className={styles.providers}>
            <legend className="visually-hidden">Provider for this run</legend>
            {data.providers.map((p) => {
              const usable = !p.needs_key || p.key_set;
              return (
                <button
                  key={p.id}
                  type="button"
                  className={styles.provider}
                  aria-pressed={chosen.provider === p.id}
                  disabled={!usable}
                  title={usable ? undefined : `Add a ${PROVIDER_NAME[p.id]} key in Settings first`}
                  onClick={() => onChange({ provider: p.id, model: p.model })}
                >
                  {PROVIDER_NAME[p.id]}
                  {!usable && <Icon name="key" size={12} />}
                </button>
              );
            })}
          </fieldset>
          <PlainTextField
            label="Model"
            value={chosen.model}
            onChange={(model) => onChange({ provider: chosen.provider, model })}
            support={`Default for ${PROVIDER_NAME[chosen.provider]}: ${provider?.default_model}.`}
          />
          {provider && !provider.on_device && (
            <p className={styles.note}>
              <Icon name="cloud" size={14} /> This sends the agent's prompts to {PROVIDER_NAME[provider.id]}.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
