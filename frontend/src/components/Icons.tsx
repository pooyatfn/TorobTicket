// Inline icons (stroke = currentColor) so they follow text colour and dark mode.
type P = { size?: number; filled?: boolean };
const svg = (size: number, children: React.ReactNode, filled = false) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor"
    strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
export const PlaneIcon = ({ size = 20 }: P) => svg(size, <path d="M10.5 21l1.5-6 5.5 2.5V15l-5.5-4V5.5a1.5 1.5 0 0 0-3 0V11L3.5 15v2.5L9 15l1.5 6zM9 21h6" transform="rotate(-90 12 12)" />);
export const TrainIcon = ({ size = 20 }: P) => svg(size, <><rect x="5" y="3" width="14" height="14" rx="3" /><path d="M5 11h14M9 21l-2-3M15 21l2-3" /><circle cx="9" cy="14" r=".6" fill="currentColor" /><circle cx="15" cy="14" r=".6" fill="currentColor" /></>);
export const BusIcon = ({ size = 20 }: P) => svg(size, <><rect x="4" y="3" width="16" height="15" rx="2.5" /><path d="M4 10h16M8 21v-3M16 21v-3" /><circle cx="8" cy="14" r=".6" fill="currentColor" /><circle cx="16" cy="14" r=".6" fill="currentColor" /></>);
export const HeartIcon = ({ size = 18, filled }: P) => svg(size, <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />, filled);
export const BellIcon = ({ size = 18 }: P) => svg(size, <><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20a2 2 0 0 0 4 0" /></>);
export const ShareIcon = ({ size = 18 }: P) => svg(size, <><circle cx="6" cy="12" r="2.2" /><circle cx="17" cy="6" r="2.2" /><circle cx="17" cy="18" r="2.2" /><path d="M8 11l7-4M8 13l7 4" /></>);
export const SearchIcon = ({ size = 20 }: P) => svg(size, <><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4-4" /></>);
export const SwapIcon = ({ size = 18 }: P) => svg(size, <path d="M7 7h11l-3-3M17 17H6l3 3" />);
export const FilterIcon = ({ size = 18 }: P) => svg(size, <path d="M4 6h16M7 12h10M10 18h4" />);
export const ChevronIcon = ({ size = 16 }: P) => svg(size, <path d="M14 6l-6 6 6 6" />);
export const CloseIcon = ({ size = 18 }: P) => svg(size, <path d="M6 6l12 12M18 6L6 18" />);
export const ClockIcon = ({ size = 16 }: P) => svg(size, <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></>);

export const ModeIcon = ({ mode, size = 20 }: { mode: "flight" | "train" | "bus"; size?: number }) =>
  mode === "flight" ? <PlaneIcon size={size} /> : mode === "train" ? <TrainIcon size={size} /> : <BusIcon size={size} />;

/** Our own mark: a ticket stub with a notch — deliberately not Torob's radish logo. */
export const Logo = ({ size = 28 }: P) => (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
    <path d="M5 8a3 3 0 0 1 3-3h16a3 3 0 0 1 3 3v4a4 4 0 0 0 0 8v4a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3v-4a4 4 0 0 0 0-8z" fill="var(--brand)" />
    <path d="M12 11h8M12 16h8M12 21h5" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
