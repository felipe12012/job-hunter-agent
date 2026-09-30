"use client";

import { Fragment, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type Status = "new" | "applied" | "interviewing" | "rejected" | "discarded";

export type Listing = {
  source: string;
  id: string;
  title: string;
  company: string | null;
  url: string;
  match_pct: number | null;
  notified: boolean;
  reasoning: string | null;
  draft_message: string | null;
  created_at: string;
  status: Status;
  user_notes: string | null;
};

const STATUS_OPTIONS: Status[] = ["new", "applied", "interviewing", "rejected", "discarded"];

type NoteSaveState = "idle" | "saving" | "saved" | "error";

function NotesEditor({
  value,
  saveState,
  errorMessage,
  onChange,
  onSave,
}: {
  value: string;
  saveState: NoteSaveState;
  errorMessage: string | null;
  onChange: (value: string) => void;
  onSave: () => void;
}) {
  return (
    <div className="mt-2">
      <p className="font-semibold text-sm mb-1">Notas</p>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border rounded px-2 py-1 text-sm"
        rows={2}
      />
      <button
        onClick={onSave}
        disabled={saveState === "saving"}
        className="mt-1 text-sm bg-black text-white rounded px-2 py-1 disabled:opacity-50"
      >
        {saveState === "saving" ? "Guardando..." : saveState === "saved" ? "Guardado" : "Guardar"}
      </button>
      {saveState === "error" && (
        <p className="text-red-600 text-sm mt-1">No se pudo guardar: {errorMessage}</p>
      )}
    </div>
  );
}

export default function ListingsTable({ listings }: { listings: Listing[] }) {
  const [source, setSource] = useState<string>("all");
  const [notifiedOnly, setNotifiedOnly] = useState(false);
  const [minMatch, setMinMatch] = useState(0);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const [statusById, setStatusById] = useState<Record<string, Status>>({});
  const [statusErrorById, setStatusErrorById] = useState<Record<string, string | null>>({});

  const [notesById, setNotesById] = useState<Record<string, string>>({});
  const [noteSaveStateById, setNoteSaveStateById] = useState<Record<string, NoteSaveState>>({});
  const [noteErrorById, setNoteErrorById] = useState<Record<string, string | null>>({});

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return listings.filter((listing) => {
      if (source !== "all" && listing.source !== source) return false;
      if (notifiedOnly && !listing.notified) return false;
      if ((listing.match_pct ?? 0) < minMatch) return false;
      if (needle) {
        const haystack = `${listing.title} ${listing.company ?? ""}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      const createdDate = listing.created_at.slice(0, 10);
      if (dateFrom && createdDate < dateFrom) return false;
      if (dateTo && createdDate > dateTo) return false;
      return true;
    });
  }, [listings, source, notifiedOnly, minMatch, search, dateFrom, dateTo]);

  async function updateStatus(listing: Listing, status: Status) {
    const key = `${listing.source}:${listing.id}`;
    const previous = statusById[key] ?? listing.status;
    setStatusById((prev) => ({ ...prev, [key]: status }));
    setStatusErrorById((prev) => ({ ...prev, [key]: null }));

    const supabase = createClient();
    const { data, error } = await supabase
      .from("listings")
      .update({ status })
      .eq("source", listing.source)
      .eq("id", listing.id)
      .select();

    // RLS blocks a mismatched update silently (0 rows, no error), so an empty
    // result is treated the same as a request error.
    if (error || !data || data.length === 0) {
      setStatusById((prev) => ({ ...prev, [key]: previous }));
      setStatusErrorById((prev) => ({
        ...prev,
        [key]: error?.message ?? "no se guardó (¿sesión vencida?)",
      }));
    }
  }

  function getNotes(listing: Listing): string {
    const key = `${listing.source}:${listing.id}`;
    return notesById[key] ?? listing.user_notes ?? "";
  }

  function setNotes(listing: Listing, value: string) {
    const key = `${listing.source}:${listing.id}`;
    setNotesById((prev) => ({ ...prev, [key]: value }));
    setNoteSaveStateById((prev) => ({ ...prev, [key]: "idle" }));
  }

  async function saveNotes(listing: Listing) {
    const key = `${listing.source}:${listing.id}`;
    const value = getNotes(listing);
    setNoteSaveStateById((prev) => ({ ...prev, [key]: "saving" }));

    const supabase = createClient();
    const { data, error } = await supabase
      .from("listings")
      .update({ user_notes: value })
      .eq("source", listing.source)
      .eq("id", listing.id)
      .select();

    if (error || !data || data.length === 0) {
      setNoteSaveStateById((prev) => ({ ...prev, [key]: "error" }));
      setNoteErrorById((prev) => ({
        ...prev,
        [key]: error?.message ?? "no se guardó (¿sesión vencida?)",
      }));
      return;
    }
    setNoteSaveStateById((prev) => ({ ...prev, [key]: "saved" }));
  }

  return (
    <div>
      <div className="flex flex-wrap gap-4 mb-4 items-center">
        <select value={source} onChange={(e) => setSource(e.target.value)} className="border rounded px-2 py-1">
          <option value="all">All sources</option>
          <option value="getonbrd">GetOnBoard</option>
          <option value="computrabajo">Computrabajo</option>
        </select>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={notifiedOnly}
            onChange={(e) => setNotifiedOnly(e.target.checked)}
          />
          Notified only
        </label>
        <label className="flex items-center gap-1">
          Min match %
          <input
            type="number"
            value={minMatch}
            onChange={(e) => setMinMatch(Number(e.target.value))}
            className="border rounded px-2 py-1 w-20"
          />
        </label>
        <input
          type="search"
          placeholder="Buscar título o empresa..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="border rounded px-2 py-1 flex-1 min-w-[200px]"
        />
        <label className="flex items-center gap-1">
          Desde
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="border rounded px-2 py-1"
          />
        </label>
        <label className="flex items-center gap-1">
          Hasta
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="border rounded px-2 py-1"
          />
        </label>
      </div>

      <p className="text-sm text-gray-500 mb-2">{filtered.length} de {listings.length} listings</p>

      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b">
            <th className="p-2">Source</th>
            <th className="p-2">Title</th>
            <th className="p-2">Company</th>
            <th className="p-2">Match %</th>
            <th className="p-2">Status</th>
            <th className="p-2">Notified</th>
            <th className="p-2">Date</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((listing) => {
            const key = `${listing.source}:${listing.id}`;
            const isExpanded = expandedKey === key;
            const status = statusById[key] ?? listing.status;
            return (
              <Fragment key={key}>
                <tr className="border-b hover:bg-gray-50">
                  <td className="p-2">{listing.source}</td>
                  <td className="p-2 cursor-pointer" onClick={() => setExpandedKey(isExpanded ? null : key)}>
                    <a href={listing.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                      {listing.title}
                    </a>
                  </td>
                  <td className="p-2">{listing.company}</td>
                  <td className="p-2">{listing.match_pct ?? "-"}</td>
                  <td className="p-2">
                    <select
                      value={status}
                      onChange={(e) => updateStatus(listing, e.target.value as Status)}
                      className="border rounded px-1 py-0.5 text-sm"
                    >
                      {STATUS_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                    {statusErrorById[key] && (
                      <p className="text-red-600 text-xs mt-0.5">{statusErrorById[key]}</p>
                    )}
                  </td>
                  <td className="p-2">{listing.notified ? "yes" : "no"}</td>
                  <td className="p-2">{new Date(listing.created_at).toLocaleDateString()}</td>
                </tr>
                {isExpanded && (
                  <tr className="border-b bg-gray-50">
                    <td colSpan={7} className="p-4">
                      <p><strong>Reasoning:</strong> {listing.reasoning ?? "n/a"}</p>
                      <p className="mt-2"><strong>Draft message:</strong> {listing.draft_message ?? "n/a"}</p>
                      <NotesEditor
                        value={getNotes(listing)}
                        saveState={noteSaveStateById[key] ?? "idle"}
                        errorMessage={noteErrorById[key] ?? null}
                        onChange={(value) => setNotes(listing, value)}
                        onSave={() => saveNotes(listing)}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
