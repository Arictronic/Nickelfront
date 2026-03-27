export const isValidEmail = (email: string) => /\S+@\S+\.\S+/.test(email);
export const isValidPassword = (password: string, minLength = 6) => password.length >= minLength;
export const isStrongPassword = (password: string) =>
  password.length >= 8;

export interface PasswordRequirements {
  minLength: boolean;
  hasUpperCase: boolean;
  hasLowerCase: boolean;
  hasNumber: boolean;
  isValid: boolean;
}

export const checkPasswordRequirements = (password: string): PasswordRequirements => {
  const minLength = password.length >= 8;
  const hasUpperCase = /[A-Z]/.test(password);
  const hasLowerCase = /[a-z]/.test(password);
  const hasNumber = /\d/.test(password);
  
  return {
    minLength,
    hasUpperCase,
    hasLowerCase,
    hasNumber,
    isValid: minLength && hasUpperCase && hasLowerCase && hasNumber,
  };
};
