import { faNum } from "./format";
import type { Mode, Trip } from "./types";

export const MODES: Mode[] = ["flight", "train", "bus"];
export const MODE_LABEL: Record<Mode, string> = { flight: "هواپیما", train: "قطار", bus: "اتوبوس" };
export const TICKET_LABEL: Record<Mode, string> = { flight: "بلیط هواپیما", train: "بلیط قطار", bus: "بلیط اتوبوس" };
export const CARRIER_LABEL: Record<Mode, string> = { flight: "ایرلاین", train: "شرکت ریلی", bus: "شرکت مسافربری" };
export const VEHICLE_LABEL: Record<Mode, string> = { flight: "هواپیما", train: "واگن", bus: "نوع اتوبوس" };

/** e.g. "ماهان ۱۱۰۱", "قطار ۳۱۸ رجا", "گیتی نورد" */
export function tripTitle(t: Trip): string {
  if (t.mode === "flight") return `${t.airline} ${t.flight_number ? `(${t.airline_code} ${faNum(t.flight_number)})` : ""}`.trim();
  if (t.mode === "train") return `قطار ${faNum(t.flight_number)}، ${t.airline}`;
  return t.airline;
}
