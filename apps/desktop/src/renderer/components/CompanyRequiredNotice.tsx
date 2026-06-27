import type { JSX } from 'react';

/**
 * The "pick a company first" placeholder shown by company-scoped screens when
 * no company is active. Centralised so the message and markup stay consistent.
 */
export function CompanyRequiredNotice(): JSX.Element {
  return (
    <section aria-live="polite">
      <p>Select or create a company first (Companies screen).</p>
    </section>
  );
}
