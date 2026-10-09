from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Customer, Order, Wallet, WalletTransaction


class WalletPaymentFlowTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='مشتری آزمایشی',
            phone='09123456789',
        )
        self.wallet = Wallet.objects.create(
            customer=self.customer,
            balance=Decimal('0'),
        )
        self.order = Order.objects.create(
            customer=self.customer,
            total_price=Decimal('25000'),
        )
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='wallet-admin',
            password='test-password',
            is_staff=True,
            is_superuser=True,
        )

    def customer_client(self):
        client = Client()
        session = client.session
        session['customer_id'] = self.customer.id
        session['customer_logged_in'] = True
        session.save()
        return client

    def test_successful_wallet_payment_returns_to_the_same_invoice(self):
        self.wallet.balance = Decimal('60000')
        self.wallet.save()

        response = self.customer_client().get(
            reverse('wallet_pay_order', args=[self.order.id])
        )

        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.order.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.wallet.balance, Decimal('35000'))
        self.assertTrue(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                order=self.order,
                transaction_type='debit',
                amount=Decimal('25000'),
            ).exists()
        )

    def test_insufficient_wallet_balance_still_returns_to_the_invoice(self):
        self.wallet.balance = Decimal('10000')
        self.wallet.save()

        response = self.customer_client().get(
            reverse('wallet_pay_order', args=[self.order.id])
        )

        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)

    def test_admin_manual_top_up_accepts_persian_grouped_amount_and_can_pay_invoice(self):
        admin_client = Client()
        admin_client.force_login(self.staff)
        response = admin_client.post(
            reverse('panel_customer_update', args=[self.customer.id]),
            {
                'name': self.customer.name,
                'phone': self.customer.phone,
                'password': '',
                'wallet_balance': '۱٬۰۰۰٬۰۰۰',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1000000'))
        self.assertTrue(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type='credit',
                amount=Decimal('1000000'),
                description='شارژ دستی توسط مدیریت',
            ).exists()
        )

        response = self.customer_client().get(
            reverse('wallet_pay_order', args=[self.order.id])
        )
        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.wallet.refresh_from_db()
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.wallet.balance, Decimal('975000'))
