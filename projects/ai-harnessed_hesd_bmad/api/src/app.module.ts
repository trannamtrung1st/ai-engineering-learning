import { Module } from '@nestjs/common';
import { HealthModule } from './modules/health/health.module';

/**
 * Future domain controllers should use:
 * @UseGuards(AuthGuard, RolesGuard) + @Roles('admin' | 'instructor' | 'student')
 * HealthModule is intentionally public (no guards).
 */
@Module({
  imports: [HealthModule],
})
export class AppModule {}
