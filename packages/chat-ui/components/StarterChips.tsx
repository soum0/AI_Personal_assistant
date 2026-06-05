const CHIPS = [
  "Why should Scaler hire you?",
  "Tell me about your OpenSearch project",
  "What's your strongest technical skill?",
  "Book a call with Soumya",
] as const;

export default function StarterChips({ onSelect }: { onSelect: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-6 py-16 select-none">
      <div className="text-center">
        <p className="text-base font-medium text-gray-300">Chat with Soumya&apos;s AI</p>
        <p className="text-sm text-gray-500 mt-1">
          Ask about his background, GitHub projects, or book a meeting.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {CHIPS.map((chip) => (
          <button
            key={chip}
            onClick={() => onSelect(chip)}
            className="text-sm px-4 py-2 rounded-full bg-gray-800 hover:bg-gray-700 active:bg-gray-600 text-gray-300 border border-gray-700 hover:border-gray-500 transition-colors"
          >
            {chip}
          </button>
        ))}
      </div>
    </div>
  );
}
