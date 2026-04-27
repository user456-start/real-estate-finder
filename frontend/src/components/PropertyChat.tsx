"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { sendChatMessage } from "@/lib/api";

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

interface PropertyChatProps {
  propertyId: string;
  propertyTitle: string;
  areaName: string | null;
  autoFocus?: boolean;
}

export default function PropertyChat({ propertyId, propertyTitle, areaName, autoFocus }: PropertyChatProps) {
  const [messages, setMessages] = useState<Message[]>([
    { role: "system", content: `You opened the listing for "${propertyTitle}" in ${areaName || "Dubai"}. Ask anything about its location, nearby amenities, or similar options.` },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [threadId, setThreadId] = useState<string | undefined>();
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (autoFocus) inputRef.current?.focus(); }, [autoFocus]);

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const send = async () => {
    const msg = input.trim();
    if (!msg || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    scrollToBottom();
    setLoading(true);
    try {
      const res = await sendChatMessage(propertyId, msg, threadId);
      setThreadId(res.thread_id);
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "Sorry, something went wrong. Please try again." }]);
    } finally {
      setLoading(false);
    }
  };

  const suggestions = [
    "How close is this to the nearest metro?",
    "What's the neighbourhood like?",
    "Find similar properties nearby",
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <h3 className="text-sm font-semibold text-gray-900">Chat about this property</h3>
        <p className="text-xs text-gray-500 mt-0.5">AI-powered answers about location, amenities, and more</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${m.role === "user" ? "bg-blue-600 text-white" : m.role === "system" ? "bg-blue-50 text-blue-800 border border-blue-200" : "bg-gray-100 text-gray-900"}`}>
              {m.role === "assistant" || m.role === "system" ? (
                <ReactMarkdown className="prose prose-sm max-w-none">
                  {m.content}
                </ReactMarkdown>
              ) : (
                <span className="whitespace-pre-wrap">{m.content}</span>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg px-3 py-2 text-sm text-gray-500 animate-pulse">Thinking...</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {messages.length <= 1 && (
        <div className="px-4 pb-2 flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button key={s} onClick={() => { setInput(s); inputRef.current?.focus(); }} className="text-xs px-2.5 py-1 rounded-full border border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100 transition-colors">
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="p-3 border-t border-gray-200 bg-white">
        <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex gap-2">
          <input ref={inputRef} type="text" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about this property..." className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent" disabled={loading} />
          <button type="submit" disabled={loading || !input.trim()} className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors">
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
