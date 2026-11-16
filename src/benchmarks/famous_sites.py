"""
Famous Sites Benchmark Pages.

Representative pages modeled after industry-leading companies (Mailchimp, Stripe,
Shopify, GitHub) demonstrating the 8-step internal linking playbook and topic
cluster architectures. The texts are illustrative paraphrases, not live crawls.
Roles and thresholds for each site live in config/sites/<site>.yaml.
"""

from typing import List
from src.connectors.sitemap_crawler import ParsedPage


def get_mailchimp_pages() -> List[ParsedPage]:
    """
    Mailchimp Case Study:
    From Borja's benchmark: 11 articles where educational guides link contextually
    to the Welcome Sequence tutorial and the Audience Segmentation product page.
    """
    return [
        ParsedPage(
            url="https://mailchimp.com/resources/email-marketing-guide/",
            title="The Ultimate Guide to Email Marketing",
            h1="Email Marketing Strategy and Best Practices",
            paragraphs=[
                "Email marketing remains the highest ROI channel for digital businesses. This comprehensive guide covers list building, sequencing, and segmentation.",
                "To start engaging new signups, create a dedicated welcome sequence that introduces your core product benefits.",
                "Organize your subscribers into groups based on their behavior using audience segmentation tools.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://mailchimp.com/resources/welcome-email-sequence-guide/",
            title="How to Build Winning Welcome Email Sequences",
            h1="Mastering Your First 14 Days of Subscriber Onboarding",
            paragraphs=[
                "A welcome email sequence is an automated series of messages sent immediately after someone subscribes to your list.",
                "Before automating the schedule, review our foundational email marketing guide to align your sequence with your brand goals.",
                "Target each email to specific subscriber interests using our audience segmentation features.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://mailchimp.com/features/audience-segmentation/",
            title="Audience Segmentation Software & Behavioral Targeting",
            h1="Deliver Personalized Campaigns with Smart Segmentation",
            paragraphs=[
                "Group your contacts by purchase history, location, or engagement score. Send the right message to the right person at the right time.",
                "Learn how to apply segments to your automated welcome email sequence to improve retention.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://mailchimp.com/pricing/",
            title="Mailchimp Plans and Pricing",
            h1="Choose the Right Plan for Growing Your Business",
            paragraphs=[
                "Compare Standard, Essentials, and Free plans. All paid plans include advanced segmentation and multi-step automated sequences.",
            ],
            existing_internal_links=[],
        ),
    ]


def get_stripe_pages() -> List[ParsedPage]:
    """
    Stripe Case Study:
    Payments pillar guide, Radar fraud prevention tutorial, Checkout money page.
    """
    return [
        ParsedPage(
            url="https://stripe.com/resources/more/guide-to-online-payments",
            title="The Complete Guide to Online Payments | Stripe Resources",
            h1="How Online Card Payments and Processing Work",
            paragraphs=[
                "Accepting payments over the internet requires an acquiring bank, a card network, and a payment processor.",
                "As transaction volumes scale, protecting your business against chargebacks requires dedicated fraud prevention algorithms.",
                "You can embed a pre-built, conversion-optimized payment form on your website using Stripe Checkout.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://stripe.com/resources/more/how-to-prevent-credit-card-fraud",
            title="How to Prevent Payment Fraud and Chargebacks | Stripe Resources",
            h1="E-commerce Fraud Prevention Strategies",
            paragraphs=[
                "Card testing and identity theft can severely damage a merchant's chargeback ratio and lead to hefty fines.",
                "Review the fundamentals of payment processing in our complete guide to online payments before setting up risk thresholds.",
                "Automate real-time risk scoring using machine learning with Radar fraud prevention.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://stripe.com/checkout",
            title="Stripe Checkout | Pre-built, Hosted Payment Page",
            h1="The Best Converting Checkout in the World",
            paragraphs=[
                "Stripe Checkout dynamically adapts to your customer's location and device with one-click payment methods like Apple Pay and Google Pay.",
                "Every transaction processed through Checkout is screened automatically by Radar fraud prevention.",
            ],
            existing_internal_links=[],
        ),
    ]


def get_shopify_pages() -> List[ParsedPage]:
    """
    Shopify Case Study:
    Ecommerce business guide, Dropshipping support post, Point of Sale (POS) money page.
    """
    return [
        ParsedPage(
            url="https://www.shopify.com/blog/how-to-start-an-ecommerce-business",
            title="How to Start an Ecommerce Business in 2026: Step-by-Step",
            h1="Building Your Online Store from Scratch",
            paragraphs=[
                "Starting an online store requires choosing a niche, sourcing products, and launching your digital storefront.",
                "If you prefer not to hold physical inventory, explore our beginner tutorial on dropshipping suppliers.",
                "For retail businesses with brick-and-mortar storefronts, sync your inventory with Shopify POS.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://www.shopify.com/blog/what-is-dropshipping",
            title="What is Dropshipping and How Does it Work?",
            h1="The Beginner's Blueprint for Dropshipping",
            paragraphs=[
                "Dropshipping allows entrepreneurs to sell products directly from third-party manufacturers without warehouse storage.",
                "Before launching your store, follow our master guide on how to start an ecommerce business to plan your legal structure.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://www.shopify.com/pos",
            title="Shopify POS | Retail Point of Sale System",
            h1="Unify Your In-Person and Online Retail Sales",
            paragraphs=[
                "Manage inventory, accept mobile contactless payments, and reward loyal customers both online and in retail locations.",
            ],
            existing_internal_links=[],
        ),
    ]


def get_github_pages() -> List[ParsedPage]:
    """
    GitHub Case Study:
    DevOps CI/CD pillar guide, Actions workflow tutorial, GitHub Enterprise money page.
    """
    return [
        ParsedPage(
            url="https://github.com/resources/articles/devops/what-is-ci-cd",
            title="What is CI/CD? Continuous Integration & Continuous Delivery",
            h1="The Modern DevOps Guide to CI/CD Pipelines",
            paragraphs=[
                "Continuous integration and continuous delivery enable development teams to test code changes and ship securely to production.",
                "Automate your testing and deployment workflows directly in your repository with GitHub Actions.",
                "For organizations requiring advanced compliance and enterprise audit logs, discover GitHub Enterprise.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://github.com/resources/articles/devops/github-actions-tutorial",
            title="Getting Started with GitHub Actions Workflows",
            h1="Automate Your Software Development Workflows",
            paragraphs=[
                "GitHub Actions connects all of your tools to automate every step of your software workflow with YAML configurations.",
                "Understand the foundational architecture of automated testing in our guide on what is CI/CD.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://github.com/enterprise",
            title="GitHub Enterprise | The AI-Powered Developer Platform",
            h1="Empower Your Entire Organization with Enterprise DevOps",
            paragraphs=[
                "Scale securely with SOC2 compliance, SAML single sign-on, fine-grained access tokens, and unlimited GitHub Actions runners.",
            ],
            existing_internal_links=[],
        ),
    ]
