// Client-side mirror of the backend password policy (backend/portal/models.py).
//
// Why duplicate it at all: the backend is the authority and will reject a weak
// password with a 422 regardless. But a 422 arrives after the form is submitted,
// which reads as a bug to the person filling it in. This lets the form say what
// is wrong while they are still typing.
//
// The two definitions MUST stay in sync. If you change one, change the other:
// minimum 8 characters, requires lowercase + uppercase + digit, symbols optional.
export const PASSWORD_MIN_LEN = 8;
export const PASSWORD_MAX_LEN = 72;

/**
 * Returns null when the password is acceptable, or a human-readable reason.
 */
export function checkPassword(pw) {
  if (!pw) return "Password wajib diisi";
  if (pw.length < PASSWORD_MIN_LEN) return `Password minimal ${PASSWORD_MIN_LEN} karakter`;
  if (pw.length > PASSWORD_MAX_LEN) return `Password maksimal ${PASSWORD_MAX_LEN} karakter`;
  const missing = [];
  if (!/[a-z]/.test(pw)) missing.push("huruf kecil");
  if (!/[A-Z]/.test(pw)) missing.push("huruf besar");
  if (!/[0-9]/.test(pw)) missing.push("angka");
  if (missing.length) return `Password harus mengandung ${missing.join(", ")} (simbol opsional)`;
  return null;
}
