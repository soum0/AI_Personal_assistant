"use client";

import type { Slot } from "@/lib/types";

interface Props {
  slots:     Slot[];
  loading:   boolean;
  onSelect:  (slot: Slot) => void;
  onDismiss: () => void;
}

export default function SlotPicker({ slots, loading, onSelect, onDismiss }: Props) {
  return (
    <div className="my-2 p-4 bg-gray-900 rounded-2xl border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-gray-300">
          {loading ? "Checking availability…" : "Pick a time slot"}
        </p>
        <button
          onClick={onDismiss}
          className="text-gray-600 hover:text-gray-400 text-lg leading-none"
          aria-label="Dismiss"
        >
          ✕
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-9 bg-gray-800 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : slots.length === 0 ? (
        <p className="text-sm text-gray-500">No open slots in the next 7 days.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 max-h-52 overflow-y-auto pr-0.5">
          {slots.map((slot, i) => (
            <button
              key={i}
              onClick={() => onSelect(slot)}
              className="text-left px-3 py-2 text-xs bg-gray-800 hover:bg-gray-700 active:bg-blue-900 text-gray-200 rounded-lg border border-gray-700 hover:border-blue-500 transition-colors"
            >
              {slot.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
