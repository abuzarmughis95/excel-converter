import { useId, type InputHTMLAttributes, type JSX } from 'react';

import { Field } from './Field.js';

type NativeInputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'value' | 'onChange' | 'type'
>;

export interface TextFieldProps extends NativeInputProps {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  type?: 'text' | 'email' | 'password' | 'date' | 'number' | 'search';
  hint?: string;
  error?: string | null;
}

/**
 * A labelled text/date/number input. Wraps the native input in a Field and
 * exposes a string value + onValueChange so screens don't repeat the
 * onChange={(e) => set(e.target.value)} boilerplate. Extra native props
 * (placeholder, min, max, autoComplete, required, disabled…) pass through.
 */
export function TextField({
  label,
  value,
  onValueChange,
  type = 'text',
  hint,
  error,
  required,
  id,
  ...rest
}: TextFieldProps): JSX.Element {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  return (
    <Field label={label} controlId={controlId} hint={hint} error={error} required={required}>
      <input
        id={controlId}
        className="ui-input"
        type={type}
        value={value}
        required={required}
        aria-invalid={
          error !== null && error !== undefined && error !== '' ? true : undefined
        }
        onChange={(e) => {
          onValueChange(e.target.value);
        }}
        {...rest}
      />
    </Field>
  );
}
