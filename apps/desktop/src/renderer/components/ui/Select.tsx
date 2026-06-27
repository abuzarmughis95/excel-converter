import { useId, type JSX, type SelectHTMLAttributes } from 'react';

import { Field } from './Field.js';

export interface SelectOption {
  value: string;
  label: string;
}

type NativeSelectProps = Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  'value' | 'onChange'
>;

export interface SelectProps extends NativeSelectProps {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  hint?: string;
  error?: string | null;
}

/**
 * A labelled dropdown. Pass options as {value,label} pairs; the value/
 * onValueChange API mirrors TextField so screens stay consistent.
 */
export function Select({
  label,
  value,
  onValueChange,
  options,
  hint,
  error,
  required,
  id,
  ...rest
}: SelectProps): JSX.Element {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  return (
    <Field label={label} controlId={controlId} hint={hint} error={error} required={required}>
      <select
        id={controlId}
        className="ui-select"
        value={value}
        onChange={(e) => {
          onValueChange(e.target.value);
        }}
        {...rest}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </Field>
  );
}
