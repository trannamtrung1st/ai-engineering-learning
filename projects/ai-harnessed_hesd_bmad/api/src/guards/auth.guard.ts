import {
  CanActivate,
  ExecutionContext,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { Request } from 'express';

export interface AuthenticatedUser {
  id: string;
  role: 'admin' | 'instructor' | 'student';
}

@Injectable()
export class AuthGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<Request>();
    const authHeader = request.headers.authorization;

    if (!authHeader?.startsWith('Bearer ')) {
      throw new UnauthorizedException(
        'Missing or invalid Authorization header',
      );
    }

    // TODO(Story 1.3): validate Supabase JWT via SUPABASE_JWT_SECRET or JWKS
    (request as Request & { user: AuthenticatedUser }).user = {
      id: 'stub',
      role: 'admin',
    };

    return true;
  }
}
