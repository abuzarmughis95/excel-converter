import { useCallback, useEffect, useRef, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { ApiError } from '../lib/api-client.js';
import { errorMessage } from '../lib/errors.js';
import type { SheetData } from '../lib/api-types.js';
import { formatMinorPlain } from '../lib/money.js';

const DEFAULT_ROWS = 20;
const DEFAULT_COLS = 8;

/** An in-memory sheet being edited. */
interface EditSheet {
  name: string;
  cells: string[][];
}

/** Build a blank grid of the given size. */
function blankGrid(rows: number, cols: number): string[][] {
  return Array.from({ length: rows }, () => Array.from({ length: cols }, () => ''));
}

/** Pad/normalize a loaded sheet's grid to at least the default size. */
function normalizeCells(cells: string[][]): string[][] {
  const rows = Math.max(cells.length, DEFAULT_ROWS);
  const cols = Math.max(DEFAULT_COLS, ...cells.map((r) => r.length), DEFAULT_COLS);
  return Array.from({ length: rows }, (_, r) =>
    Array.from({ length: cols }, (_, c) => cells[r]?.[c] ?? ''),
  );
}

/** Trim trailing empty rows/cols before saving so the payload stays small. */
function trimGrid(cells: string[][]): string[][] {
  let lastRow = -1;
  let lastCol = -1;
  for (let r = 0; r < cells.length; r++) {
    const row = cells[r] ?? [];
    for (let c = 0; c < row.length; c++) {
      if ((row[c] ?? '') !== '') {
        if (r > lastRow) {
          lastRow = r;
        }
        if (c > lastCol) {
          lastCol = c;
        }
      }
    }
  }
  if (lastRow < 0) {
    return [];
  }
  return cells.slice(0, lastRow + 1).map((row) => row.slice(0, lastCol + 1));
}

function columnLabel(index: number): string {
  let n = index;
  let label = '';
  do {
    label = String.fromCharCode(65 + (n % 26)) + label;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return label;
}

/**
 * Spreadsheet screen: a multi-sheet workbook for the active company. Add/rename/
 * delete sheets (tabs), edit cells, and press Ctrl+S to save the whole workbook
 * to the backend (so it syncs across devices). The dirty state is tracked and
 * shown; saving clears it.
 */
export function SpreadsheetScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [sheets, setSheets] = useState<EditSheet[]>([]);
  const [active, setActive] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pdfInput = useRef<HTMLInputElement>(null);
  // Keep the latest state available to the keydown handler without re-binding.
  const stateRef = useRef<{ companyId: string | null; sheets: EditSheet[] }>({
    companyId,
    sheets: [],
  });

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      const wb = await api.loadWorkbook(companyId);
      const loaded: EditSheet[] = wb.sheets
        .slice()
        .sort((a: SheetData, b: SheetData) => a.sort_order - b.sort_order)
        .map((s: SheetData) => ({ name: s.name, cells: normalizeCells(s.cells) }));
      setSheets(loaded.length > 0 ? loaded : [{ name: 'Sheet1', cells: blankGrid(DEFAULT_ROWS, DEFAULT_COLS) }]);
      setActive(0);
      setDirty(false);
    } catch (err) {
      setError(errorMessage(err, 'Failed to load workbook.'));
    }
  }, [api, companyId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const save = useCallback(async (): Promise<void> => {
    const { companyId: cid, sheets: current } = stateRef.current;
    if (cid === null || current.length === 0) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.saveWorkbook(cid, {
        sheets: current.map((s) => ({ name: s.name, cells: trimGrid(s.cells) })),
      });
      setDirty(false);
      setStatus('Saved');
      setTimeout(() => {
        setStatus(null);
      }, 1500);
    } catch (err) {
      setError(errorMessage(err, 'Failed to save workbook.'));
    } finally {
      setSaving(false);
    }
  }, [api]);

  // Keep the ref current for the global Ctrl+S handler.
  useEffect(() => {
    stateRef.current = { companyId, sheets };
  }, [companyId, sheets]);

  // Ctrl+S / Cmd+S saves the workbook.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        void save();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [save]);

  function updateCell(row: number, col: number, value: string): void {
    setSheets((prev) =>
      prev.map((s, i) =>
        i === active
          ? { ...s, cells: s.cells.map((r, ri) => (ri === row ? r.map((c, ci) => (ci === col ? value : c)) : r)) }
          : s,
      ),
    );
    setDirty(true);
  }

  function addSheet(): void {
    const existing = new Set(sheets.map((s) => s.name));
    let n = sheets.length + 1;
    while (existing.has(`Sheet${String(n)}`)) {
      n += 1;
    }
    setSheets((prev) => [...prev, { name: `Sheet${String(n)}`, cells: blankGrid(DEFAULT_ROWS, DEFAULT_COLS) }]);
    setActive(sheets.length);
    setDirty(true);
  }

  function renameSheet(index: number): void {
    const next = window.prompt('Sheet name', sheets[index]?.name ?? '');
    if (next === null || next.trim() === '') {
      return;
    }
    setSheets((prev) => prev.map((s, i) => (i === index ? { ...s, name: next.trim() } : s)));
    setDirty(true);
  }

  function deleteSheet(index: number): void {
    if (sheets.length <= 1) {
      return;
    }
    setSheets((prev) => prev.filter((_, i) => i !== index));
    setActive((a) => (a >= index && a > 0 ? a - 1 : a));
    setDirty(true);
  }

  function addRow(): void {
    setSheets((prev) =>
      prev.map((s, i) =>
        i === active ? { ...s, cells: [...s.cells, Array.from({ length: s.cells[0]?.length ?? DEFAULT_COLS }, () => '')] } : s,
      ),
    );
    setDirty(true);
  }

  const fromMinor = (minor: number): string => formatMinorPlain(minor, { blankZero: true });

  /** Upload a PDF, extract it, and drop the rows into a NEW editable sheet. */
  async function importPdf(file: File): Promise<void> {
    if (companyId === null) {
      return;
    }
    setImporting(true);
    setError(null);
    try {
      const extracted = await api.extractStatement(companyId, file);
      const header = ['Date', 'Description', 'Money out', 'Money in', 'Balance'];
      const rows = extracted.lines.map((ln) => [
        ln.date ?? '',
        ln.description,
        fromMinor(ln.money_out_minor),
        fromMinor(ln.money_in_minor),
        ln.balance_minor !== null ? fromMinor(ln.balance_minor) : '',
      ]);
      // Pad to a minimum grid so the user has room to edit.
      const cells = [header, ...rows];
      while (cells.length < DEFAULT_ROWS) {
        cells.push(Array.from({ length: header.length }, () => ''));
      }
      // Derive a unique sheet name from the file.
      const base = file.name.replace(/\.pdf$/i, '').slice(0, 40) || 'Imported';
      const existing = new Set(sheets.map((s) => s.name));
      let name = base;
      let suffix = 2;
      while (existing.has(name)) {
        name = `${base} ${String(suffix)}`;
        suffix += 1;
      }
      setSheets((prev) => [...prev, { name, cells }]);
      setActive(sheets.length);
      setDirty(true);
      setStatus(`Imported ${String(extracted.lines.length)} rows into "${name}". Press Ctrl+S to save.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError('PDF import is not configured on the server (no OpenAI API key).');
      } else {
        setError(errorMessage(err, 'Failed to import the PDF.'));
      }
    } finally {
      setImporting(false);
    }
  }

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  const current = sheets[active];

  return (
    <section aria-live="polite" className="sheet-screen">
      <div className="sheet-toolbar">
        <button type="button" onClick={() => void save()} disabled={saving} className="sheet-save">
          {saving ? 'Saving…' : 'Save'} <span className="sheet-shortcut">Ctrl+S</span>
        </button>
        <button type="button" onClick={addRow}>
          + Row
        </button>
        <input
          ref={pdfInput}
          type="file"
          accept="application/pdf"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f !== undefined) {
              void importPdf(f);
            }
            e.target.value = '';
          }}
        />
        <button
          type="button"
          onClick={() => {
            pdfInput.current?.click();
          }}
          disabled={importing}
        >
          {importing ? 'Importing…' : 'Import PDF'}
        </button>
        <span className="sheet-status">
          {error !== null ? (
            <span className="unbalanced">{error}</span>
          ) : status !== null ? (
            <span className="balanced">{status}</span>
          ) : dirty ? (
            <span className="unbalanced">Unsaved changes</span>
          ) : (
            <span style={{ opacity: 0.6 }}>All changes saved</span>
          )}
        </span>
      </div>

      {current !== undefined && (
        <div className="sheet-grid-wrap">
          <table className="sheet-grid">
            <thead>
              <tr>
                <th className="sheet-corner" />
                {(current.cells[0] ?? []).map((_, c) => (
                  <th key={c}>{columnLabel(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {current.cells.map((row, r) => (
                <tr key={r}>
                  <th className="sheet-rownum">{r + 1}</th>
                  {row.map((cell, c) => (
                    <td key={c}>
                      <input
                        type="text"
                        value={cell}
                        onChange={(e) => {
                          updateCell(r, c, e.target.value);
                        }}
                        aria-label={`${columnLabel(c)}${String(r + 1)}`}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="sheet-tabs">
        {sheets.map((s, i) => (
          <div key={i} className={i === active ? 'sheet-tab active' : 'sheet-tab'}>
            <button
              type="button"
              onClick={() => {
                setActive(i);
              }}
              onDoubleClick={() => {
                renameSheet(i);
              }}
              title="Double-click to rename"
            >
              {s.name}
            </button>
            {sheets.length > 1 && (
              <button
                type="button"
                className="sheet-tab-close"
                onClick={() => {
                  deleteSheet(i);
                }}
                aria-label={`Delete ${s.name}`}
              >
                ×
              </button>
            )}
          </div>
        ))}
        <button type="button" className="sheet-tab-add" onClick={addSheet} aria-label="Add sheet">
          +
        </button>
      </div>
    </section>
  );
}
