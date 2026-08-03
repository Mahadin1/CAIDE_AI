/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '*.supabase.co' },
      { protocol: 'https', hostname: 'avatars.githubusercontent.com' },
    ],
  },
  allowedDevOrigins: ['.monkeycode-ai.live'],
  experimental: {
    allowedHosts: ['.monkeycode-ai.live'],
  },
}

module.exports = nextConfig
