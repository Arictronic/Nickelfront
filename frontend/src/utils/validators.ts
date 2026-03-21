export const isValidEmail = (email: string) => /\S+@\S+\.\S+/.test(email);
export const isValidPassword = (password: string, minLength = 6) => password.length >= minLength;
export const isStrongPassword = (password: string) =>
  password.length >= 8 && /[A-Z]/.test(password) && /[a-z]/.test(password) && /\d/.test(password);
