<p align="center">
  <img src="assets/restaura-banner.png" alt="Restaura: AI agents for your restaurant" width="100%">
</p>

# Restaura

AI agents for restaurants. Built for the HUMAIN Hackathon, Challenge 3: Autonomous Enterprise.

Restaura is a web app where AI agents each own a whole process in a restaurant, and the manager only approves what spends money or changes records.

## The two agents

**1. Cashier helper.** While an order is taken, it suggests add-ons and upgrades that fit the order, hides items that are out of stock, and shows the manager in real time what is helping sales.

**2. Stock-to-order agent.** After the branch closes it takes the day's sales and, using each item's recipe, works out how much of every ingredient was used. It keeps an estimated stock level, notices when an ingredient falls below the minimum the manager set, and drafts the supplier order. The manager approves it with one tap and the order goes to the supplier by email. Deliveries are logged from a photo of the supplier invoice, and a monthly count corrects the estimate.

The agents share one database: what the cashier sells drives what the stock agent orders, and what runs out is hidden at the cashier.

Planned next: staff shifts and attendance, daily and monthly routines, sales forecasting, expenses, a manager overview and supplier ordering by WhatsApp.

## Status

In development for the hackathon (deadline 30 October 2026). It is a demo for one store, using sample data, test recipes and a built-in demo cashier screen. Real supplier invoices and menus are not committed to this public repository.

## Planned stack

Python and FastAPI, PostgreSQL, a React and TypeScript web app (responsive for laptop and phone), and the Anthropic Claude API for the agents.

## Secrets

No keys or `.env` files are committed. The Anthropic API key is supplied as an environment variable. See `.gitignore`.

## Brand

Name, logo and colors are in [docs/BRAND.md](docs/BRAND.md). Palette: Slate `#1F2937`, Silver `#B7BFCC`, Cloud `#F8FAFC`.

## Author

Yousef Samman
