/**
 * The product's identity in the app's chrome (RIDGELINE-01 P7; SPEC R-11, R-13).
 *
 * A product name is not a project name: the chrome stays project-neutral, and the project's own
 * name still arrives from the period data. These strings mirror `src/final/product.py`, and
 * `tests/test_ridgeline01_app_chrome.py` fails if they drift apart.
 */
export const PRODUCT_NAME = "Ridgeline";
export const TAGLINE =
  "Ridgeline: cost and schedule risk for capital projects, from bid to handover";
export const MAKER = "CBL Analytics";
/** The brand line: the tagline, then who makes it (R-13). */
export const PRODUCT_LINE = `${TAGLINE}. A ${MAKER} product.`;
