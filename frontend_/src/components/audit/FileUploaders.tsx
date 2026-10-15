import { useCallback, useId, useState } from 'react'
import { FileArchive, FileText, Link as LinkIcon, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { formatBytes } from '@/lib/utils'
import { cn } from '@/lib/utils'

interface UploaderProps {
  label: string
  required?: boolean
  accept: string
  hint: string
  file: File | null
  error?: string
  onChange: (file: File | null) => void
  kind: 'apk' | 'policy'
  hideLabel?: boolean
  emptyTitle?: string
  disabled?: boolean
}

export function FileUploader({ label, required, accept, hint, file, error, onChange, kind, hideLabel, emptyTitle, disabled }: UploaderProps) {
  const [dragOver, setDragOver] = useState(false)
  const inputId = useId()
  const Icon = kind === 'apk' ? FileArchive : FileText
  const EmptyIcon = kind === 'apk' ? Upload : FileText

  const handleFiles = useCallback(
    (list: FileList | null) => {
      if (disabled) return
      const next = list?.[0]
      if (!next) return
      onChange(next)
    },
    [disabled, onChange],
  )

  return (
    <div className={hideLabel ? 'h-full' : 'flex h-full flex-col'}>
      {hideLabel ? null : (
        <p className="pg-label">
          {label} {required ? <span className="text-danger">*</span> : null}
        </p>
      )}
      {file ? (
        <div className={cn(
          'flex items-center justify-between rounded-xl border border-line bg-white px-4 py-4 dark:border-night-border dark:bg-night-raised',
          hideLabel && 'h-full min-h-[220px]',
          kind === 'apk' && 'flex-1',
        )}>
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-lg bg-primary/10 text-primary">
              <Icon size={18} />
            </span>
            <div>
              <p className="text-sm font-semibold text-ink">{file.name}</p>
              <p className="text-xs text-muted">{formatBytes(file.size)}</p>
            </div>
          </div>
          <button type="button" className="rounded-md p-1 text-muted hover:bg-subtle" aria-label="Remove file" onClick={() => onChange(null)}>
            <X size={16} />
          </button>
        </div>
      ) : (
        <div
          className={cn(
            'rounded-xl border-2 border-dashed px-4 py-8 text-center transition',
            hideLabel && 'flex h-full min-h-[220px] flex-col items-center justify-center',
            kind === 'apk' && 'flex min-h-0 flex-1 flex-col items-center justify-center',
            dragOver && !disabled ? 'border-primary bg-primary/5' : 'border-line bg-subtle/60 dark:border-night-border dark:bg-night-raised',
            error && 'border-danger',
            disabled && 'pointer-events-none opacity-50',
          )}
          onDragOver={(event) => {
            if (disabled) return
            event.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            if (disabled) return
            event.preventDefault()
            setDragOver(false)
            handleFiles(event.dataTransfer.files)
          }}
        >
          <EmptyIcon className="mx-auto text-primary" size={22} />
          <p className="mt-3 text-sm font-medium text-ink">{emptyTitle ?? 'Drag and drop your file here'}</p>
          <p className="mt-1 text-xs text-muted">{hint}</p>
          <input id={inputId} type="file" accept={accept} disabled={disabled} className="sr-only" onChange={(event) => handleFiles(event.target.files)} />
          <Button type="button" size="sm" className="mt-4" disabled={disabled} onClick={() => document.getElementById(inputId)?.click()}>
            Choose File
          </Button>
        </div>
      )}
      {error ? <p className="mt-1.5 text-xs font-medium text-danger">{error}</p> : null}
    </div>
  )
}

export function ApkUploader(props: Omit<UploaderProps, 'kind' | 'accept' | 'hint' | 'label'> & { label?: string }) {
  return (
    <FileUploader
      kind="apk"
      label={props.label ?? 'APK Upload'}
      required
      accept=".apk,application/vnd.android.package-archive"
      hint="Android APK files only"
      file={props.file}
      error={props.error}
      onChange={props.onChange}
    />
  )
}

export function PrivacyPolicyUploader({
  file,
  onChange,
  error,
  url,
  onUrlChange,
  urlError,
}: Omit<UploaderProps, 'kind' | 'accept' | 'hint' | 'label'> & {
  url: string
  onUrlChange: (url: string) => void
  urlError?: string
}) {
  const hasFile = Boolean(file)
  const hasUrl = Boolean(url.trim())

  return (
    <div>
      <p className="pg-label">
        Privacy Policy <span className="text-danger">*</span>
      </p>
      <div className="grid items-stretch gap-3 sm:grid-cols-[1fr_auto_1fr] sm:gap-0">
        <FileUploader
          kind="policy"
          label="Privacy Policy"
          hideLabel
          emptyTitle="Upload Privacy Policy"
          accept=".pdf,.txt,.doc,.docx,application/pdf,text/plain"
          hint="PDF, TXT, or DOC files only"
          file={file}
          onChange={onChange}
          disabled={hasUrl}
        />
        <div className="relative flex min-h-8 items-center justify-center py-1 sm:mx-1 sm:w-10">
          <span className="absolute inset-x-8 top-1/2 h-px bg-line dark:bg-night-border sm:inset-x-auto sm:inset-y-4 sm:left-1/2 sm:h-auto sm:w-px" />
          <span className="relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border border-line bg-white text-[10px] font-bold tracking-wide text-muted dark:border-night-border dark:bg-night-card">
            OR
          </span>
        </div>
        <div
          className={cn(
            'flex min-h-[220px] flex-col items-center justify-center rounded-xl border border-line bg-subtle/80 px-4 py-6 text-center dark:border-night-border dark:bg-night-raised/70',
            urlError && 'border-danger',
            hasFile && 'opacity-50',
          )}
        >
          <LinkIcon className="text-primary" size={22} />
          <p className="mt-3 text-sm font-medium text-ink">Provide Privacy Policy Link</p>
          <label className="relative mt-4 block w-full max-w-[260px] text-left">
            <LinkIcon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={15} />
            <input
              name="privacyPolicyLink"
              value={url}
              onChange={(event) => onUrlChange(event.target.value)}
              placeholder="https://yourprivacy..."
              aria-label="Privacy Policy URL"
              aria-invalid={Boolean(urlError)}
              disabled={hasFile}
              className={cn('pg-input pl-9', urlError && 'border-danger focus:border-danger focus:ring-danger/15', hasFile && 'cursor-not-allowed')}
            />
          </label>
          {urlError ? (
            <p className="mt-1.5 w-full max-w-[260px] text-left text-xs font-medium text-danger">{urlError}</p>
          ) : (
            <p className="mt-1.5 w-full max-w-[260px] text-left text-xs text-muted">Enter the URL to your Privacy Policy page</p>
          )}
        </div>
      </div>
      {error ? <p className="mt-1.5 text-xs font-medium text-danger">{error}</p> : null}
    </div>
  )
}
