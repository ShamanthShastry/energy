// The mark: a vertical bolt. Used small in the header and sign-in, and page-high in the intro.
export function Bolt({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 40" aria-hidden="true" focusable="false">
      <path d="M14.5 0 L2 23 H10.5 L8 40 L22 16 H13.5 Z" fill="currentColor" />
    </svg>
  );
}
