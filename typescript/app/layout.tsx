import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import Providers from '@/components/providers';
import { cn } from '@/lib/utils';
import Link from 'next/link';
import {
  LayoutDashboard,
  List,
  Settings,
  Play,
  MessageSquare,
  Sliders,
  ShieldAlert,
} from 'lucide-react';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Freelancer Automation',
  description: 'AI-powered Freelancer Automation Dashboard',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh">
      <body className={cn(inter.className, 'bg-gray-50 text-gray-900')}>
        <Providers>
          <div className="flex h-screen w-full">
            {/* Sidebar */}
            <aside className="w-64 bg-white border-r border-gray-200 hidden md:flex flex-col">
              <div className="p-6 border-b border-gray-100">
                <h1 className="text-xl font-bold text-blue-600">Freelancer AI</h1>
              </div>
              <nav className="flex-1 p-4 space-y-2">
                <Link
                  href="/"
                  className="flex items-center gap-3 px-3 py-2 text-gray-700 hover:bg-blue-50 hover:text-blue-600 rounded-md transition-colors"
                >
                  <LayoutDashboard size={20} />
                  <span>仪表盘</span>
                </Link>
                <Link
                  href="/projects"
                  className="flex items-center gap-3 px-3 py-2 text-gray-700 hover:bg-blue-50 hover:text-blue-600 rounded-md transition-colors"
                >
                  <List size={20} />
                  <span>项目列表</span>
                </Link>
                <Link
                  href="/prompts"
                  className="flex items-center gap-3 px-3 py-2 text-gray-700 hover:bg-blue-50 hover:text-blue-600 rounded-md transition-colors"
                >
                  <MessageSquare size={20} />
                  <span>提示词管理</span>
                </Link>
                <Link
                  href="/scoring"
                  className="flex items-center gap-3 px-3 py-2 text-gray-700 hover:bg-blue-50 hover:text-blue-600 rounded-md transition-colors"
                >
                  <Sliders size={20} />
                  <span>评分配置</span>
                </Link>
                <Link
                  href="/risk"
                  className="flex items-center gap-3 px-3 py-2 text-gray-700 hover:bg-blue-50 hover:text-blue-600 rounded-md transition-colors"
                >
                  <ShieldAlert size={20} />
                  <span>客户风控</span>
                </Link>
                <Link
                  href="/scripts"
                  className="flex items-center gap-3 px-3 py-2 text-gray-700 hover:bg-blue-50 hover:text-blue-600 rounded-md transition-colors"
                >
                  <Play size={20} />
                  <span>脚本控制</span>
                </Link>
                <Link
                  href="/settings"
                  className="flex items-center gap-3 px-3 py-2 text-gray-700 hover:bg-blue-50 hover:text-blue-600 rounded-md transition-colors"
                >
                  <Settings size={20} />
                  <span>系统设置</span>
                </Link>
              </nav>
            </aside>

            {/* Main Content */}
            <main className="flex-1 overflow-auto p-8">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
