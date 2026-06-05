"use client";

import { useEffect, useRef, useState } from "react";
import ChatBubble      from "@/components/ChatBubble";
import TypingIndicator from "@/components/TypingIndicator";
import StarterChips    from "@/components/StarterChips";
import SlotPicker      from "@/components/SlotPicker";
import BookingForm     from "@/components/BookingForm";
import type { Message, Slot, BookingResult } from "@/lib/types";

const BOOKING_RE = /\b(book|schedule|availab|meeting|call\s+with|slot|calendar)\b/i;

type BookingPhase = "idle" | "loading-slots" | "selecting" | "form" | "booking" | "confirmed";

let _n = 0;
const uid = () => `m${++_n}`;

export default function ChatPage() {
  const [messages,      setMessages]     = useState<Message[]>([]);
  const [input,         setInput]        = useState("");
  const [streaming,     setStreaming]     = useState(false);
  const [streamText,    setStreamText]    = useState("");
  const [sessionId]                       = useState(() => Math.random().toString(36).slice(2, 10));

  const [phase,         setPhase]         = useState<BookingPhase>("idle");
  const [slots,         setSlots]         = useState<Slot[]>([]);
  const [selectedSlot,  setSelectedSlot]  = useState<Slot | null>(null);
  const [bookingResult, setBookingResult] = useState<BookingResult | null>(null);
  const [bookingError,  setBookingError]  = useState("");

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamText, phase]);

  // ── Booking helpers ───────────────────────────────────────────────────────

  async function fetchSlots() {
    setPhase("loading-slots");
    setBookingError("");
    try {
      const res  = await fetch("/api/availability");
      const data = await res.json() as { slots?: Slot[] };
      setSlots(data.slots ?? []);
      setPhase("selecting");
    } catch {
      setPhase("idle");
    }
  }

  async function handleBook(name: string, email: string) {
    if (!selectedSlot) return;
    setPhase("booking");
    setBookingError("");
    try {
      const res  = await fetch("/api/book", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          slot:           selectedSlot.start,
          attendee_name:  name,
          attendee_email: email,
        }),
      });
      const data = await res.json() as BookingResult & { detail?: string };
      if (!data.confirmed) throw new Error(data.detail ?? "Not confirmed");

      setBookingResult(data);
      setPhase("confirmed");
      setMessages((prev) => [
        ...prev,
        {
          id:      uid(),
          role:    "assistant",
          content: `Your meeting is confirmed for ${selectedSlot.label}! A calendar invite has been sent to ${email}.`,
          sources: [],
        },
      ]);
    } catch (err: unknown) {
      setBookingError(err instanceof Error ? err.message : "Booking failed");
      setPhase("form");
    }
  }

  // ── Send message ──────────────────────────────────────────────────────────

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || streaming) return;

    setInput("");
    setStreaming(true);
    setStreamText("");

    const userMsg: Message = { id: uid(), role: "user", content: trimmed };
    setMessages((prev) => [...prev, userMsg]);

    const wantsBooking = BOOKING_RE.test(trimmed);
    const history      = messages.map((m) => ({ role: m.role, content: m.content }));

    try {
      const res = await fetch("/api/chat", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          message:              trimmed,
          session_id:           sessionId,
          conversation_history: history,
        }),
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buf        = "";
      let fullText   = "";
      let sources:   string[] = [];
      let done       = false;

      while (!done) {
        const { done: eof, value } = await reader.read();
        if (eof) break;

        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(part.slice(6)) as { t?: string; done?: boolean; sources?: string[] };
            if (ev.done) {
              sources = ev.sources ?? [];
              done    = true;
              break;
            }
            if (ev.t) {
              fullText += ev.t;
              setStreamText(fullText);
            }
          } catch { /* skip malformed line */ }
        }
      }

      setMessages((prev) => [
        ...prev,
        { id: uid(), role: "assistant", content: fullText, sources },
      ]);
      setStreamText("");
      if (wantsBooking && phase === "idle") fetchSlots();

    } catch {
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: "assistant", content: "Something went wrong. Please try again.", sources: [] },
      ]);
      setStreamText("");
    } finally {
      setStreaming(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <main className="flex flex-col h-screen max-w-2xl mx-auto">
      {/* Header */}
      <header className="shrink-0 px-5 py-3 border-b border-gray-800 flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-gray-200">Soumya&apos;s AI Representative</h1>
          <p className="text-xs text-gray-600">RAG-grounded · claude-sonnet-4</p>
        </div>
        <span className="text-xs text-gray-700 hidden sm:block">ai-persona</span>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent">
        {messages.length === 0 && !streaming && (
          <StarterChips onSelect={sendMessage} />
        )}

        {messages.map((msg) => (
          <ChatBubble key={msg.id} message={msg} />
        ))}

        {streaming && <TypingIndicator text={streamText} />}

        {/* Booking flow — inline below messages */}
        {(phase === "loading-slots" || phase === "selecting") && (
          <SlotPicker
            slots={slots}
            loading={phase === "loading-slots"}
            onSelect={(slot) => { setSelectedSlot(slot); setPhase("form"); }}
            onDismiss={() => setPhase("idle")}
          />
        )}

        {(phase === "form" || phase === "booking") && selectedSlot && (
          <BookingForm
            slot={selectedSlot}
            loading={phase === "booking"}
            error={bookingError}
            onSubmit={handleBook}
            onBack={() => setPhase("selecting")}
          />
        )}

        {phase === "confirmed" && bookingResult && (
          <div className="my-2 p-4 bg-gray-900 rounded-2xl border border-green-800">
            <p className="text-sm font-medium text-green-400 mb-2">Meeting confirmed!</p>
            {bookingResult.meet_link && (
              <a
                href={bookingResult.meet_link}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:underline break-all block mb-1"
              >
                Google Meet: {bookingResult.meet_link}
              </a>
            )}
            {bookingResult.event_link && (
              <a
                href={bookingResult.event_link}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-gray-500 hover:text-gray-400 block mb-2"
              >
                View calendar event →
              </a>
            )}
            <button
              onClick={() => { setPhase("idle"); setBookingResult(null); }}
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
            >
              Dismiss
            </button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 px-5 py-3 border-t border-gray-800">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage(input);
              }
            }}
            placeholder="Ask anything about Soumya…"
            disabled={streaming}
            autoFocus
            className="flex-1 bg-gray-800 border border-gray-700 focus:border-blue-500 rounded-xl px-4 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none disabled:opacity-50 transition-colors"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={streaming || !input.trim()}
            className="bg-blue-600 hover:bg-blue-700 active:bg-blue-800 disabled:opacity-40 rounded-xl px-5 py-2 text-sm font-medium text-white transition-colors"
          >
            Send
          </button>
        </div>
      </div>
    </main>
  );
}
