import type { ButtonHTMLAttributes, JSX } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

/**
 * A themed button. `variant` selects the colour treatment (primary = parrot
 * green, secondary/ghost = outline, danger = red). `type` defaults to "button"
 * so it never accidentally submits a form.
 */
export function Button({
  variant = 'primary',
  type = 'button',
  className,
  children,
  ...rest
}: ButtonProps): JSX.Element {
  const classes = ['ui-button', `ui-button-${variant}`, className]
    .filter(Boolean)
    .join(' ');
  return (
    <button
      type={type === 'submit' ? 'submit' : type === 'reset' ? 'reset' : 'button'}
      className={classes}
      {...rest}
    >
      {children}
    </button>
  );
}
