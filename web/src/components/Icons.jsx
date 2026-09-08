/** Hand-rolled 16px stroke icons - no icon library dependency. */

const base = {
  width: 16,
  height: 16,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.9,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

const make = (paths) =>
  function Icon({ size = 16, ...rest }) {
    return (
      <svg {...base} width={size} height={size} aria-hidden="true" {...rest}>
        {paths}
      </svg>
    )
  }

export const IconBars = make(
  <>
    <path d="M4 20V13" />
    <path d="M10 20V6" />
    <path d="M16 20V10" />
    <path d="M22 20V4" />
  </>,
)

export const IconSend = make(<path d="M4 12h15M13 6l6 6-6 6" />)

export const IconSparkle = make(
  <>
    <path d="M12 3.5 13.6 9 19 10.5 13.6 12 12 17.5 10.4 12 5 10.5 10.4 9z" />
    <path d="M18.5 16.5 19.2 19 21.5 19.7 19.2 20.4 18.5 22.9 17.8 20.4 15.5 19.7 17.8 19z" />
  </>,
)

export const IconUpload = make(
  <>
    <path d="M12 16V4" />
    <path d="m7 9 5-5 5 5" />
    <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
  </>,
)

export const IconDatabase = make(
  <>
    <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
    <path d="M4.5 5.5v13c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-13" />
    <path d="M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3" />
  </>,
)

export const IconClose = make(<path d="M6 6l12 12M18 6L6 18" />)

export const IconChevron = make(<path d="m9 5 7 7-7 7" />)

export const IconCopy = make(
  <>
    <rect x="9" y="9" width="12" height="12" rx="2.2" />
    <path d="M15 5.5A2.5 2.5 0 0 0 12.5 3H5.5A2.5 2.5 0 0 0 3 5.5v7A2.5 2.5 0 0 0 5.5 15" />
  </>,
)

export const IconDownload = make(
  <>
    <path d="M12 4v11" />
    <path d="m7 10 5 5 5-5" />
    <path d="M4 19h16" />
  </>,
)

export const IconRefresh = make(
  <>
    <path d="M20.5 11a8.5 8.5 0 1 0-.9 5" />
    <path d="M21 5.5V11h-5.5" />
  </>,
)

export const IconSearch = make(
  <>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-3.7-3.7" />
  </>,
)

export const IconFilter = make(<path d="M3.5 5h17l-6.5 8v6l-4 2v-8z" />)

export const IconLayers = make(
  <>
    <path d="m12 3 9 5-9 5-9-5z" />
    <path d="m3.5 12.5 8.5 4.7 8.5-4.7" />
    <path d="m3.5 17 8.5 4.7 8.5-4.7" />
  </>,
)

export const IconTable = make(
  <>
    <rect x="3" y="4" width="18" height="16" rx="2.2" />
    <path d="M3 9.5h18M9 9.5V20" />
  </>,
)

export const IconGauge = make(
  <>
    <path d="M4 18a8 8 0 1 1 16 0" />
    <path d="m12 14 4-3.5" />
  </>,
)

export const IconMessage = make(
  <path d="M20 14.5a2.5 2.5 0 0 1-2.5 2.5H9l-4.5 3.5V6.5A2.5 2.5 0 0 1 7 4h10.5A2.5 2.5 0 0 1 20 6.5z" />,
)

export const IconShield = make(
  <>
    <path d="M12 3 20 6v6c0 4.5-3.2 7.9-8 9.5-4.8-1.6-8-5-8-9.5V6z" />
    <path d="m9 12 2 2 4-4" />
  </>,
)

export const IconSun = make(
  <>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2.5 12h2M19.5 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />
  </>,
)

export const IconMoon = make(<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5" />)

export const IconPanel = make(
  <>
    <rect x="3" y="4" width="18" height="16" rx="2.2" />
    <path d="M9.5 4v16" />
  </>,
)

export const IconAlert = make(
  <>
    <path d="M12 8v5" />
    <path d="M12 16.5h.01" />
    <circle cx="12" cy="12" r="9" />
  </>,
)

export const IconTrash = make(
  <>
    <path d="M4 7h16" />
    <path d="M9 7V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v2" />
    <path d="M6.5 7 7.5 20a1.5 1.5 0 0 0 1.5 1.4h6a1.5 1.5 0 0 0 1.5-1.4L17.5 7" />
  </>,
)

export const IconPlus = make(<path d="M12 5v14M5 12h14" />)

export const IconFile = make(
  <>
    <path d="M14 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V8z" />
    <path d="M14 3v5h5" />
  </>,
)
