// Shows three bouncing dots before the first token, then renders the partial text
// with a blinking cursor appended.
export default function TypingIndicator({ text }: { text: string }) {
  if (!text) {
    return (
      <div className="flex justify-start">
        <div className="rounded-2xl rounded-bl-sm px-4 py-3 bg-gray-800">
          <div className="flex gap-1 items-center h-4">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce"
                style={{ animationDelay: `${i * 160}ms` }}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="rounded-2xl rounded-bl-sm px-4 py-2.5 bg-gray-800 text-gray-100 text-sm leading-relaxed whitespace-pre-wrap max-w-[82%]">
        {text}
        <span className="inline-block w-px h-3.5 bg-blue-400 ml-0.5 animate-pulse align-text-bottom" />
      </div>
    </div>
  );
}
