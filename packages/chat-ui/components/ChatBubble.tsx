"use client";

import { useState } from "react";
import type { Message } from "@/lib/types";

export default function ChatBubble({ message }: { message: Message }) {
  const [open, setOpen] = useState(false);
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`flex flex-col gap-1 max-w-[82%] ${isUser ? "items-end" : "items-start"}`}>
        {/* Bubble */}
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? "bg-blue-600 text-white rounded-br-sm"
              : "bg-gray-800 text-gray-100 rounded-bl-sm"
          }`}
        >
          {message.content}
        </div>

        {/* Sources toggle */}
        {!isUser && message.sources && message.sources.length > 0 && (
          <>
            <button
              onClick={() => setOpen((v) => !v)}
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors px-1 flex items-center gap-1"
            >
              <span>{open ? "▾" : "▸"}</span>
              <span>
                {message.sources.length} source{message.sources.length !== 1 ? "s" : ""}
              </span>
            </button>

            {open && (
              <div className="flex flex-wrap gap-1 px-1">
                {message.sources.map((src, i) => (
                  <span
                    key={i}
                    className="text-xs bg-gray-900 text-gray-400 border border-gray-700 px-2 py-0.5 rounded-full"
                  >
                    {src}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
