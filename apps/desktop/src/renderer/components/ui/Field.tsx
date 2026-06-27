import type { JSX, ReactNode } from 'react';

/**
 * A labelled form field. Renders a <label htmlFor={controlId}> as a sibling of
 * the control (passed as children), which is the most robust association for
 * assistive tech and testing-library's getByLabelText. Also renders optional
 * hint/error text. TextField/Select generate the id and pass it through.
 */
export interface FieldProps {
  label: string;
  /** id of the control this label points at (set by the wrapping control). */
  controlId: string;
  hint?: string | undefined;
  error?: string | null | undefined;
  required?: boolean | undefined;
  children: ReactNode;
}

export function Field({
  label,
  controlId,
  hint,
  error,
  required,
  children,
}: FieldProps): JSX.Element {
  return (
    <div className="ui-field">
      <label
        className={required === true ? 'ui-field-label ui-field-label-required' : 'ui-field-label'}
        htmlFor={controlId}
      >
        {label}
      </label>
      {children}
      {hint !== undefined && (error === null || error === undefined) && (
        <span className="ui-field-hint">{hint}</span>
      )}
      {error !== null && error !== undefined && error !== '' && (
        <span className="ui-field-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
