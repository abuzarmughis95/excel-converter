import type { FormHTMLAttributes, JSX, ReactNode } from 'react';

export interface FormProps extends Omit<FormHTMLAttributes<HTMLFormElement>, 'onSubmit'> {
  /** Called on submit with the default already prevented. */
  onSubmit: () => void;
  children: ReactNode;
}

/**
 * A form wrapper that calls onSubmit with preventDefault already handled, so
 * screens stop repeating `(e) => { e.preventDefault(); ... }`.
 */
export function Form({ onSubmit, children, className, ...rest }: FormProps): JSX.Element {
  return (
    <form
      className={['ui-form', className].filter(Boolean).join(' ')}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      {...rest}
    >
      {children}
    </form>
  );
}
