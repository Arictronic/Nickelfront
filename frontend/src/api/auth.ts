export async function login(email: string, password: string) {
  if (!email || password.length < 6) {
    throw new Error("Некорректный email или пароль");
  }
  return { email };
}

export async function register(email: string, password: string) {
  if (!email || password.length < 8) {
    throw new Error("Пароль должен быть не менее 8 символов");
  }
  return { email };
}
