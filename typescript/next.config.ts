import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // 环境变量配置（客户端可访问）
  env: {
    NEXT_PUBLIC_APP_NAME: 'Freelancer Automation',
    NEXT_PUBLIC_APP_VERSION: '1.0.0',
  },

  // 启用实验性功能
  experimental: {
    serverActions: {
      bodySizeLimit: '2mb',
    },
  },

  // 图片优化配置
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**',
      },
    ],
    // 允许的图片格式
    formats: ['image/avif', 'image/webp'],
    // 设备尺寸配置
    deviceSizes: [640, 750, 828, 1080, 1200, 1920, 2048, 3840],
    imageSizes: [16, 32, 48, 64, 96, 128, 256, 384],
  },

  // 输出配置
  output: 'standalone',

  // 静态页面生成配置
  trailingSlash: false,

  // Headers 安全配置
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'X-DNS-Prefetch-Control',
            value: 'on',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'X-Frame-Options',
            value: 'SAMEORIGIN',
          },
          {
            key: 'X-XSS-Protection',
            value: '1; mode=block',
          },
          {
            key: 'Referrer-Policy',
            value: 'origin-when-cross-origin',
          },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
        ],
      },
    ];
  },

  // 重定向配置
  async redirects() {
    return [
      // 添加其他重定向规则
    ];
  },
};

export default nextConfig;
