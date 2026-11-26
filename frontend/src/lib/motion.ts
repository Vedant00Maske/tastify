/**
 * Shared motion values (DESIGN.md, Components > Motion). Reduced motion is handled globally by
 * `<MotionConfig reducedMotion="user">` and the CSS rule in globals.css.
 */

/** `--ease-out-soft`: page enters, dialogs, list reveals. */
export const easeOutSoft = [0.22, 1, 0.36, 1] as const;

/**
 * The toggle spring: press, toggle and reveal responses (a selection sliding between options).
 * Damping ratio about 0.76, so it settles with one small overshoot.
 */
export const springToggle = {
  type: "spring",
  stiffness: 500,
  damping: 34,
  mass: 1,
} as const;
