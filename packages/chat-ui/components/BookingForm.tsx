"use client";

import { useState } from "react";
import type { Slot } from "@/lib/types";

interface Props {
  slot:      Slot;
  loading:   boolean;
  error:     string;
  onSubmit:  (name: string, email: string) => void;
  onBack:    () => void;
}

export default function BookingForm({ slot, loading, error, onSubmit, onBack }: Props) {
  const [name,  setName]  = useState("");
  const [email, setEmail] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (name.trim() && email.trim()) onSubmit(name.trim(), email.trim());
  }

  return (
    <div className="my-2 p-4 bg-gray-900 rounded-2xl border border-gray-700">
      <div className="flex items-center gap-2 mb-1">
        <button
          onClick={onBack}
          disabled={loading}
          className="text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-40"
          aria-label="Back"
        >
          ←
        </button>
        <p className="text-sm font-medium text-gray-300">Confirm booking</p>
      </div>

      <p className="text-xs text-gray-500 mb-3 pl-6">{slot.label}</p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <input
          type="text"
          placeholder="Your name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={loading}
          required
          className="bg-gray-800 border border-gray-700 focus:border-blue-500 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none transition-colors disabled:opacity-50"
        />
        <input
          type="email"
          placeholder="Your email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={loading}
          required
          className="bg-gray-800 border border-gray-700 focus:border-blue-500 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none transition-colors disabled:opacity-50"
        />

        {error && <p className="text-xs text-red-400 px-1">{error}</p>}

        <button
          type="submit"
          disabled={loading || !name.trim() || !email.trim()}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors"
        >
          {loading ? "Booking…" : "Confirm meeting"}
        </button>
      </form>
    </div>
  );
}
