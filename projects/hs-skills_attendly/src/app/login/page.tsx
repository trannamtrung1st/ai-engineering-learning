type LoginPageProps = {
  searchParams: Promise<{ error?: string; next?: string }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const { error, next } = await searchParams;

  return (
    <main>
      <h1>Sign in to Attendly</h1>
      {error ? <p role="alert">Invalid email or password.</p> : null}
      <form action="/api/auth/login" method="post">
        <input type="hidden" name="next" value={next ?? ""} />
        <label>
          Email
          <input name="email" type="email" required autoComplete="email" />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            required
            autoComplete="current-password"
          />
        </label>
        <button type="submit">Sign in</button>
      </form>
      <p>Demo password: attendly-demo</p>
    </main>
  );
}
