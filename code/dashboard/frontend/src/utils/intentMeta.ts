export const INTENT_LABELS: Record<string, string> = {
  greeting:          '\u6253\u62db\u547c',
  interview_invite:  '\u9762\u8bd5\u9080\u8bf7',
  rejection:         '\u5df2\u62d2\u7edd',
  info_request:      '\u8bf7\u6c42\u4fe1\u606f',
  salary_discussion: '\u85aa\u8d44\u6d3d\u8c08',
  offer:             'Offer',
  general_inquiry:   '\u4e00\u822c\u8be2\u95ee',
  general_notice:    '\u4e00\u822c\u901a\u77e5',
  other:             '\u5176\u4ed6',
}

// Apple dark-mode system signal palette (matches tailwind signal-* tokens).
export const INTENT_COLORS: Record<string, string> = {
  interview_invite:  '#30d158',
  rejection:         '#ff453a',
  offer:             '#ffd60a',
  info_request:      '#0a84ff',
  salary_discussion: '#bf5af2',
  greeting:          '#84848c',
  general_inquiry:   '#0a84ff',
  general_notice:    '#84848c',
  other:             '#84848c',
}
