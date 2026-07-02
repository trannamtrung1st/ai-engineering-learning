import postgres from 'postgres';
export declare function createDbClient(connectionString?: string | undefined): import("drizzle-orm/postgres-js").PostgresJsDatabase<Record<string, never>> & {
    $client: postgres.Sql<{}>;
};
