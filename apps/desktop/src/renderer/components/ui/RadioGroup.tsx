import { useId, type JSX } from 'react';

export interface RadioOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface RadioGroupProps {
  /** Group label (rendered as the fieldset legend). */
  legend: string;
  value: string;
  onValueChange: (value: string) => void;
  options: RadioOption[];
  /** Lay the radios out horizontally instead of stacked. */
  inline?: boolean;
  name?: string;
}

/**
 * An accessible radio group. Renders a fieldset/legend with one radio per
 * option; value/onValueChange mirror the other controls.
 */
export function RadioGroup({
  legend,
  value,
  onValueChange,
  options,
  inline,
  name,
}: RadioGroupProps): JSX.Element {
  const generatedName = useId();
  const groupName = name ?? generatedName;
  return (
    <fieldset className={inline === true ? 'ui-radiogroup ui-radiogroup-inline' : 'ui-radiogroup'}>
      <legend className="ui-field-label">{legend}</legend>
      {options.map((opt) => (
        <label key={opt.value} className="ui-radio">
          <input
            type="radio"
            name={groupName}
            value={opt.value}
            checked={value === opt.value}
            disabled={opt.disabled}
            onChange={() => {
              onValueChange(opt.value);
            }}
          />
          <span>{opt.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
