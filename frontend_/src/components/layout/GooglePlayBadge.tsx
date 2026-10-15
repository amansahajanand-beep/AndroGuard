import googlePlayIcon from '@/assets/google-play.svg'

export function GooglePlayBadge() {
  return (
    <div className="flex items-center gap-3">
      <img src={googlePlayIcon} alt="" className="h-8 w-8 shrink-0 object-contain" aria-hidden="true" />
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold text-white">Google Play</span>
        <span className="block text-[12px] font-normal text-[#8696A8]">Compliance &amp; Secure</span>
      </span>
    </div>
  )
}
