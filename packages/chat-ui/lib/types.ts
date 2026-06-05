export interface Message {
  id:       string;
  role:     "user" | "assistant";
  content:  string;
  sources?: string[];
}

export interface Slot {
  start: string;  // ISO 8601
  end:   string;
  label: string;  // human-readable, e.g. "Mon 10 Jun, 10:00 AM IST"
}

export interface BookingResult {
  confirmed:  boolean;
  event_link: string;
  meet_link:  string;
}
