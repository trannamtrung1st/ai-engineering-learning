import { CanActivate, ExecutionContext } from '@nestjs/common';
export interface AuthenticatedUser {
    id: string;
    role: 'admin' | 'instructor' | 'student';
}
export declare class AuthGuard implements CanActivate {
    canActivate(context: ExecutionContext): boolean;
}
