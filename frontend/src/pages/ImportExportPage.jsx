import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, Download, ShieldCheck, FileSpreadsheet, CheckCircle2 } from 'lucide-react'
import { api, downloadFile, errorMessage } from '../services/api'
import { useToast } from '../context/ToastContext'
import { Alert, Badge, Card, PageHeader, Spinner } from '../components/ui'
import { dateTime, num } from '../utils/format'

const MAX_KB = 1024
const FIELDS = [
  { key: 'ticker', label: 'Stock symbol / ticker' },
  { key: 'quantity', label: 'Quantity' },
  { key: 'avg_price', label: 'Average buy price' },
]

function Steps({ step }) {
  const labels = ['Upload', 'Map & validate', 'Import']
  return (
    <ol className="steps" aria-label="Import progress">
      {labels.map((l, i) => (
        <li key={l} className={`step ${i < step ? 'done' : i === step ? 'current' : ''}`} aria-current={i === step ? 'step' : undefined}>
          <b>{i < step ? '✓' : i + 1}</b>{l}{i < labels.length - 1 && <span className="muted" aria-hidden="true"> ›</span>}
        </li>
      ))}
    </ol>
  )
}

export default function ImportExportPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState(null)
  const [upload, setUpload] = useState(null)
  const [mapping, setMapping] = useState(null)
  const [validation, setValidation] = useState(null)
  const [mode, setMode] = useState('replace')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [exporting, setExporting] = useState(false)

  const step = result ? 3 : upload ? 1 : 0

  const handleFile = useCallback(async (file) => {
    setError(null); setResult(null)
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.csv')) return setError('Please choose a .csv file.')
    if (file.size > MAX_KB * 1024) return setError(`File is larger than ${MAX_KB} KB.`)
    setProgress(0)
    try {
      const res = await api.uploadCsv(file, setProgress)
      setUpload(res); setMapping(res.mapping); setValidation(res.validation)
    } catch (err) {
      setError(errorMessage(err, 'Upload failed.'))
    } finally { setProgress(null) }
  }, [])

  const changeMapping = async (key, value) => {
    const next = { ...mapping, [key]: value || null, confidence: 'manual' }
    setMapping(next)
    setBusy(true)
    try { setValidation(await api.validateImport(upload.upload_id, next)) }
    catch (err) { setError(errorMessage(err)) }
    finally { setBusy(false) }
  }

  const confirm = async () => {
    setBusy(true); setError(null)
    try {
      const res = await api.confirmImport(upload.upload_id, mapping, mode)
      setResult(res); setUpload(null)
      toast(`Imported ${res.imported} holdings.`)
    } catch (err) {
      setError(errorMessage(err, 'Import failed.'))
    } finally { setBusy(false) }
  }

  const cancel = async () => {
    if (upload) { try { await api.cancelImport(upload.upload_id) } catch { /* already expired */ } }
    setUpload(null); setMapping(null); setValidation(null); setError(null)
    toast('Upload discarded and deleted from the server.', 'info')
  }

  const doExport = async () => {
    setExporting(true)
    try { const name = await downloadFile('/imports/export/holdings.csv', 'foliolens-holdings.csv'); toast(`Downloaded ${name}.`) }
    catch (err) { toast(errorMessage(err, 'Export failed.'), 'error') }
    finally { setExporting(false) }
  }

  return (
    <div className="stack">
      <PageHeader title="CSV Import & Export" subtitle="Bring in holdings from Zerodha, Groww, Upstox or any CSV" />
      <div className="grid grid-2-1">
        <Card title="Import portfolio CSV">
          <Steps step={step} />
          {error && <div style={{ marginBottom: 12 }}><Alert level="error">{error}</Alert></div>}

          {step === 0 && (
            <>
              <div className={`dropzone ${dragging ? 'active' : ''}`} role="button" tabIndex={0}
                   aria-label="Choose a CSV file to upload, or drop it here"
                   onClick={() => inputRef.current?.click()}
                   onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), inputRef.current?.click())}
                   onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
                   onDragLeave={() => setDragging(false)}
                   onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]) }}>
                {progress !== null ? <><Spinner label="Uploading" /><div style={{ width: 220 }} className="progress"><div style={{ width: `${progress}%` }} /></div><span>Uploading & validating… {progress}%</span></> : <>
                  <Upload size={26} className="muted" />
                  <strong>Drop your CSV here or click to browse</strong>
                  <span className="muted small">.csv only · max {MAX_KB} KB · needs symbol, quantity and average price columns</span>
                </>}
              </div>
              <input ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => { handleFile(e.target.files[0]); e.target.value = '' }} />
            </>
          )}

          {step === 1 && mapping && (
            <div className="stack">
              <div className="row-wrap">
                <FileSpreadsheet size={16} /><strong>{upload.filename}</strong>
                <span className="muted small">{upload.row_count} rows · {num(upload.size_bytes / 1024, 1)} KB</span>
                <Badge tone={mapping.confidence === 'high' ? 'pos' : 'warn'}>
                  {mapping.confidence === 'high' ? 'Columns auto-detected' : mapping.confidence === 'manual' ? 'Manual mapping' : 'Check column mapping'}
                </Badge>
              </div>
              <div className="grid grid-3">
                {FIELDS.map(f => (
                  <div className="field" key={f.key}>
                    <label htmlFor={`map-${f.key}`}>{f.label}</label>
                    <select id={`map-${f.key}`} className="input" value={mapping[f.key] || ''} disabled={busy}
                            onChange={(e) => changeMapping(f.key, e.target.value)}>
                      <option value="">— select column —</option>
                      {upload.columns.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                ))}
              </div>

              <div>
                <div className="card-title" style={{ marginBottom: 6 }}>File preview (first rows)</div>
                <div className="table-wrap card">
                  <table className="table">
                    <thead><tr>{upload.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
                    <tbody>{upload.preview_rows.map((r, i) => <tr key={i}>{upload.columns.map(c => <td key={c}>{r[c]}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              </div>

              {validation && (
                <div className="stack" style={{ gap: 8 }} aria-live="polite">
                  {validation.message && <Alert level="warning">{validation.message}</Alert>}
                  {validation.valid_count > 0 && <Alert level="success">{validation.valid_count} valid holdings ready to import{validation.error_count ? `; ${validation.error_count} row(s) will be skipped` : ''}.</Alert>}
                  {validation.warnings.map(w => <Alert key={w} level="info">{w}</Alert>)}
                  {validation.errors.length > 0 && (
                    <details className="card card-pad">
                      <summary style={{ cursor: 'pointer', fontWeight: 600 }}>{validation.error_count} row(s) with problems</summary>
                      <table className="table" style={{ marginTop: 8 }}>
                        <thead><tr><th>Line</th><th>Ticker</th><th>Problem</th></tr></thead>
                        <tbody>{validation.errors.map(e => <tr key={e.line}><td>{e.line}</td><td>{e.ticker}</td><td>{e.problems.join(', ')}</td></tr>)}</tbody>
                      </table>
                    </details>
                  )}
                  {validation.valid_preview?.length > 0 && (
                    <div className="table-wrap card">
                      <table className="table">
                        <thead><tr><th>Ticker</th><th className="num">Quantity</th><th className="num">Avg price</th></tr></thead>
                        <tbody>{validation.valid_preview.map(r => <tr key={r.ticker}><td>{r.ticker}</td><td className="num">{num(r.quantity, 4)}</td><td className="num">{num(r.avg_buy_price, 4)}</td></tr>)}</tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              <fieldset className="row-wrap" style={{ border: 'none' }}>
                <legend className="small muted" style={{ marginBottom: 4 }}>Import mode</legend>
                <label className="row"><input type="radio" name="mode" value="replace" checked={mode === 'replace'} onChange={() => setMode('replace')} /> Replace my current holdings</label>
                <label className="row"><input type="radio" name="mode" value="merge" checked={mode === 'merge'} onChange={() => setMode('merge')} /> Merge (update matching tickers, keep others)</label>
              </fieldset>
              <div className="row" style={{ justifyContent: 'flex-end' }}>
                <span className="muted small spacer">Staged upload expires {dateTime(upload.expires_at)}</span>
                <button className="btn" onClick={cancel} disabled={busy}>Cancel</button>
                <button className="btn btn-primary" onClick={confirm} disabled={busy || !validation?.ready}>
                  {busy ? 'Importing & resolving symbols…' : `Import ${validation?.valid_count || 0} holdings`}
                </button>
              </div>
            </div>
          )}

          {step === 3 && result && (
            <div className="stack">
              <Alert level="success"><strong>Import complete.</strong> {result.added} added, {result.updated} updated, {result.skipped} skipped ({result.mode}).</Alert>
              {result.unresolved.length > 0 && <Alert level="warning">No market listing found for {result.unresolved.join(', ')}. These are saved but show as unpriced until a listing is found (tickers may have changed after a merger or demerger).</Alert>}
              <div className="row">
                <button className="btn btn-primary" onClick={() => navigate('/portfolio')}><CheckCircle2 size={15} /> View portfolio</button>
                <button className="btn" onClick={() => setResult(null)}>Import another file</button>
              </div>
            </div>
          )}
        </Card>

        <div className="stack">
          <Card title="Export holdings">
            <p className="muted" style={{ marginBottom: 12 }}>Download your holdings with current prices as CSV. The file can be re-imported here.</p>
            <button className="btn" onClick={doExport} disabled={exporting}><Download size={15} /> {exporting ? 'Preparing…' : 'Download holdings CSV'}</button>
            <p className="hint" style={{ marginTop: 8 }}>Cells starting with = + - @ are prefixed with ' to prevent spreadsheet formula injection.</p>
          </Card>
          <Card title={<span className="row"><ShieldCheck size={16} /> How your file is protected</span>}>
            <ul className="list-dot small">
              <li>Validated for type, size, encoding, columns and every row before anything is saved.</li>
              <li>While awaiting confirmation, the file is stored only as AES-256-GCM ciphertext tied to your account.</li>
              <li>Deleted when you import or cancel, and automatically after 30 minutes.</li>
              <li>Only your account can preview, import or export your data.</li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  )
}
