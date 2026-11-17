/** Turn API error payloads, including FastAPI validation arrays, into safe text. */
export function readableErrorMessage(payload, fallback) {
  const visited = new WeakSet();

  const collect = (value) => {
    if (typeof value === "string") {
      const text = value.trim();
      return text && text !== "[object Object]" ? [text] : [];
    }
    if (Array.isArray(value)) return value.flatMap(collect);
    if (!value || typeof value !== "object") return [];
    if (visited.has(value)) return [];
    visited.add(value);

    if (typeof value.msg === "string" && Array.isArray(value.loc)) {
      const path = value.loc
        .filter((part) => part !== "body" && part !== "query" && part !== "path")
        .map((part, index, parts) =>
          typeof part === "number"
            ? `[${part}]`
            : `${index > 0 && typeof parts[index - 1] === "number" ? "." : ""}${part}`,
        )
        .join("");
      return [`${path ? `${path}: ` : ""}${value.msg}`];
    }

    const messages = [];
    for (const key of ["detail", "message", "msg", "error", "errors", "data", "response"]) {
      if (key in value) messages.push(...collect(value[key]));
    }
    return messages;
  };

  return [...new Set(collect(payload))].join("; ") || fallback;
}
