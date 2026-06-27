import { useId, type JSX } from 'react';

export interface CheckboxProps {
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  id?: string;
}

/**
 * A labelled checkbox. The label sits beside the box and is clickable. Exposes a
 * boolean checked + onCheckedChange so screens don't repeat onChange handlers.
 */
export function Checkbox({
  label,
  checked,
  onCheckedChange,
  disabled,
  id,
}: CheckboxProps): JSX.Element {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  return (
    <label className="ui-checkbox" htmlFor={inputId}>
      <input
        id={inputId}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => {
          onCheckedChange(e.target.checked);
        }}
      />
      <span>{label}</span>
    </label>
  );
}
