import { Badge } from '@/components/ui/Badge'
import { Card, CardHeader } from '@/components/ui/Card'
import { cn } from '@/lib/utils'
import type { AdAnalysis, AdPositionName, AdScreenReport, AdSightingItem } from '@/types'

const POSITION_LABEL: Record<AdPositionName, string> = {
  top: 'Top',
  bottom: 'Bottom',
  middle: 'Middle',
  fullscreen: 'Full screen',
  unknown: 'Unknown',
}

const TYPE_STYLE: Record<string, string> = {
  banner: 'border-info bg-info/25',
  native: 'border-success bg-success/25',
  interstitial: 'border-danger bg-danger/25',
  rewarded: 'border-warning bg-warning/25',
  app_open: 'border-high bg-high/25',
}

function typeStyle(adType: string) {
  return TYPE_STYLE[adType] ?? 'border-muted bg-muted/25'
}

function titleCase(value: string) {
  return value.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Phone outline with each ad drawn where it sat on the screen. */
function PlacementDiagram({ sightings }: { sightings: AdSightingItem[] }) {
  return (
    <div
      className="relative aspect-[9/19] w-24 shrink-0 overflow-hidden rounded-xl border-2 border-line bg-subtle dark:border-night-border"
      role="img"
      aria-label="Where ads appeared on this screen"
    >
      {sightings.map((item, index) => {
        const box = item.bbox ?? (item.isFullscreen ? [0, 0, 1, 1] : null)
        if (!box) return null
        return (
          <span
            key={index}
            className={cn('absolute border', typeStyle(item.adType))}
            style={{
              left: `${box[0] * 100}%`,
              top: `${box[1] * 100}%`,
              width: `${box[2] * 100}%`,
              height: `${box[3] * 100}%`,
            }}
          />
        )
      })}
    </div>
  )
}

function Screenshot({ url, alt }: { url?: string; alt: string }) {
  if (!url) return null
  return (
    <img
      src={url}
      alt={alt}
      loading="lazy"
      className="aspect-[9/19] w-20 shrink-0 rounded-lg border border-line object-cover dark:border-night-border"
      onError={(event) => {
        event.currentTarget.style.display = 'none'
      }}
    />
  )
}

function ScreenCard({ screen }: { screen: AdScreenReport }) {
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">{screen.page}</h3>
          <p className="mt-1 text-xs text-muted">
            {screen.sightings.length} placement{screen.sightings.length === 1 ? '' : 's'} ·{' '}
            {screen.positionsSeen.map((p) => POSITION_LABEL[p]).join(', ')}
          </p>
        </div>
        {screen.positionChanged ? <Badge tone="warning">Ad position changed</Badge> : null}
      </div>

      <div className="mt-4 flex flex-wrap gap-4">
        <PlacementDiagram sightings={screen.sightings} />
        {screen.screenshotUrl ? <Screenshot url={screen.screenshotUrl} alt={`${screen.page} screenshot`} /> : null}
        <ol className="min-w-[220px] flex-1 space-y-2">
          {screen.sightings.map((item, index) => (
            <li
              key={index}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line px-3 py-2 text-sm dark:border-night-border"
            >
              <span className="w-14 font-mono text-xs font-semibold tabular-nums text-muted">{item.offsetSeconds.toFixed(1)}s</span>
              <Badge tone={item.isFullscreen ? 'danger' : 'info'}>{titleCase(item.adType)}</Badge>
              <span className="font-medium text-ink">{POSITION_LABEL[item.position]}</span>
              {item.coverage !== null ? (
                <span className="text-xs text-muted">{Math.round(item.coverage * 100)}% of screen</span>
              ) : null}
              {item.screenshotUrl ? (
                <a
                  href={item.screenshotUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-auto text-xs font-semibold text-primary"
                >
                  View frame
                </a>
              ) : null}
            </li>
          ))}
        </ol>
      </div>
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 font-mono text-2xl font-bold tabular-nums text-ink">{value}</p>
    </Card>
  )
}

export function AdPlacementReport({ analysis }: { analysis?: AdAnalysis }) {
  if (!analysis || !analysis.explored) {
    return (
      <Card>
        <CardHeader title="Ad Placements" />
        <p className="px-5 py-4 text-sm text-muted">
          The app was not explored on an emulator, so ad placements were not captured. Run an audit with exploration
          enabled to see where ads appear on each screen.
        </p>
      </Card>
    )
  }
  if (!analysis.screens.length) {
    return (
      <Card>
        <CardHeader title="Ad Placements" />
        <p className="px-5 py-4 text-sm text-muted">No advertising was detected on the screens the agent visited.</p>
      </Card>
    )
  }

  const positions = (Object.keys(POSITION_LABEL) as AdPositionName[]).filter((p) => analysis.positionCounts[p])
  const moved = analysis.screens.filter((s) => s.positionChanged).length

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Screens with ads" value={analysis.screens.length} />
        <Stat label="Placements seen" value={analysis.totalPlacements} />
        <Stat label="Full-screen ads" value={analysis.fullscreenCount} />
        <Stat label="Screens where ads moved" value={moved} />
      </div>
      <Card className="flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3 text-sm">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">By position</span>
        {positions.map((p) => (
          <span key={p} className="text-ink">
            {POSITION_LABEL[p]} <strong className="tabular-nums">{analysis.positionCounts[p]}</strong>
          </span>
        ))}
      </Card>
      {analysis.screens.map((screen) => (
        <ScreenCard key={screen.stateId} screen={screen} />
      ))}
    </div>
  )
}
