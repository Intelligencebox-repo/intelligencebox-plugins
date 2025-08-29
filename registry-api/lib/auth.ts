import { NextRequest } from 'next/server';

export function checkAdminAuth(request: NextRequest): boolean {
  const authHeader = request.headers.get('authorization');
  
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return false;
  }
  
  const password = authHeader.substring(7);
  const adminPassword = process.env.ADMIN_PASSWORD || 'default-password-change-me';
  
  return password === adminPassword;
}