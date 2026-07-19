import { useEffect, useState } from 'react';

/**
 * Flagpost mark.
 *
 * Renders the logo, optionally with the "Plant" animation (LOGO-SPEC.md §11).
 *
 * The animation is gated to once per session. A failed sign-in re-renders the
 * page, and watching the flag plant itself repeatedly while fighting a
 * password manager turns charm into friction.
 *
 * Requires flagpost-plant.css.
 *
 *   <FlagpostMark size={42} animate theme="dark" />
 */

const SESSION_KEY = 'fp:plant-played';

const PALETTE = {
  light: { post: '#101720', flag: '#1F9E6B' },
  dark:  { post: '#E4E7E2', flag: '#2CB57C' },
};

export default function FlagpostMark({
  size = 64,
  animate = false,
  theme = 'light',
  once = true,
  className = '',
  title = 'Flagpost',
}) {
  const [shouldAnimate, setShouldAnimate] = useState(false);

  useEffect(() => {
    if (!animate) return;

    if (!once) {
      setShouldAnimate(true);
      return;
    }

    // sessionStorage can throw in private-mode / sandboxed contexts.
    // Failing to read it should never prevent the logo from rendering.
    let alreadyPlayed = false;
    try {
      alreadyPlayed = window.sessionStorage.getItem(SESSION_KEY) === '1';
    } catch {
      alreadyPlayed = false;
    }

    if (alreadyPlayed) return;

    setShouldAnimate(true);
    try {
      window.sessionStorage.setItem(SESSION_KEY, '1');
    } catch {
      /* non-fatal — the animation just plays again next load */
    }
  }, [animate, once]);

  const colors = PALETTE[theme] ?? PALETTE.light;

  // Below 32px the ground ellipse reads as a smear. See LOGO-SPEC.md §1.2.
  const isSmall = size < 32;

  return (
    <svg
      className={`fp-mark ${className}`.trim()}
      data-animate={shouldAnimate ? 'plant' : undefined}
      data-size={isSmall ? 'sm' : undefined}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={title}
    >
      {!isSmall && (
        <ellipse
          className="fp-ground"
          cx="22"
          cy="55"
          rx="12"
          ry="3.2"
          fill={colors.post}
        />
      )}
      <rect
        className="fp-post"
        x="19"
        y="6"
        width="6"
        height="49"
        rx="3"
        fill={colors.post}
      />
      <path
        className="fp-flag"
        d="M25 9 H46 L40.5 16 L46 23 H25 Z"
        fill={colors.flag}
      />
    </svg>
  );
}

/**
 * Clears the session gate. Useful in Storybook, visual regression runs, or a
 * brand page where the animation is the subject rather than the chrome.
 */
export function resetPlantAnimation() {
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* no-op */
  }
}
