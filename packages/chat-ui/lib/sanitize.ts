// Patterns that signal prompt injection attempts.
// Strip before forwarding to persona-api.
const PATTERNS: RegExp[] = [
  /ignore\s+(all\s+)?previous\s+instructions?/gi,
  /system\s+prompt/gi,
  /jailbreak/gi,
  /forget\s+(your\s+)?instructions?/gi,
  /pretend\s+you\s+are/gi,
  /act\s+as\s+(?!Soumya)/gi,
  /do\s+anything\s+now/gi,
  /you\s+are\s+now\s+(?!Soumya)/gi,
];

export function sanitize(input: string): string {
  return PATTERNS.reduce(
    (text, pat) => text.replace(pat, "[redacted]"),
    input,
  ).trim();
}
