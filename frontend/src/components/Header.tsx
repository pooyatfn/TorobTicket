import { HeartIcon, BellIcon, Logo } from "./Icons";
import ModeTabs from "./ModeTabs";
import { linkProps, navigate } from "../lib/router";
import type { Mode } from "../lib/types";

export default function Header({ mode, children }: { mode: Mode; children?: React.ReactNode }) {
  return (
    <header className="top">
      <div className={"wrap wide top-row" + (children ? " with-search" : "")}>
        <a className="brandmark" {...linkProps(`/?mode=${mode}`)}><Logo /><span>ترب <b>تیکت</b></span></a>
        <div className="top-search">{children}</div>
        <nav className="top-links">
          <a {...linkProps("/favorites")}><HeartIcon /><span>علاقه‌مندی‌ها</span></a>
          <a {...linkProps("/alerts")}><BellIcon /><span>هشدارهای من</span></a>
        </nav>
      </div>
      <div className="wrap wide cat-row">
        <ModeTabs mode={mode} onChange={(m) => navigate(`/?mode=${m}`)} />
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="foot">
      <div className="wrap">
        <span>ترب تیکت مقایسه قیمت است و بلیط نمی‌فروشد؛ خرید در سایت فروشنده انجام می‌شود.</span>
        <span className="muted">قیمت‌ها برای یک بزرگسال است و ممکن است در سایت فروشنده تغییر کرده باشد.</span>
      </div>
    </footer>
  );
}
