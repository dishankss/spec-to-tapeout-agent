module seq_detector_0011 (clk,
    data_in,
    detected,
    reset);
 input clk;
 input data_in;
 output detected;
 input reset;

 wire _0_;
 wire _1_;
 wire _2_;
 wire _3_;
 wire _4_;
 wire net1;
 wire net3;
 wire net2;
 wire \shift_reg[0] ;
 wire \shift_reg[1] ;
 wire \shift_reg[2] ;
 wire clknet_0_clk;
 wire clknet_1_0__leaf_clk;
 wire clknet_1_1__leaf_clk;

 sky130_fd_sc_hd__nor2b_2 _5_ (.A(net2),
    .B_N(\shift_reg[0] ),
    .Y(_0_));
 sky130_fd_sc_hd__and2b_2 _6_ (.A_N(net2),
    .B(net1),
    .X(_1_));
 sky130_fd_sc_hd__nor2_1 _7_ (.A(\shift_reg[1] ),
    .B(\shift_reg[2] ),
    .Y(_4_));
 sky130_fd_sc_hd__and3_1 _8_ (.A(net1),
    .B(_0_),
    .C(_4_),
    .X(_2_));
 sky130_fd_sc_hd__and2b_2 _9_ (.A_N(net2),
    .B(\shift_reg[1] ),
    .X(_3_));
 sky130_fd_sc_hd__clkbuf_4 clkbuf_0_clk (.A(clk),
    .X(clknet_0_clk));
 sky130_fd_sc_hd__clkbuf_4 clkbuf_1_0__f_clk (.A(clknet_0_clk),
    .X(clknet_1_0__leaf_clk));
 sky130_fd_sc_hd__clkbuf_4 clkbuf_1_1__f_clk (.A(clknet_0_clk),
    .X(clknet_1_1__leaf_clk));
 sky130_fd_sc_hd__dfxtp_1 \detected$_SDFF_PP0_  (.D(_2_),
    .Q(net3),
    .CLK(clknet_1_1__leaf_clk));
 sky130_fd_sc_hd__clkdlybuf4s50_1 input1 (.A(data_in),
    .X(net1));
 sky130_fd_sc_hd__clkdlybuf4s50_1 input2 (.A(reset),
    .X(net2));
 sky130_fd_sc_hd__clkdlybuf4s50_1 output3 (.A(net3),
    .X(detected));
 sky130_fd_sc_hd__dfxtp_1 \shift_reg[0]$_SDFF_PP0_  (.D(_1_),
    .Q(\shift_reg[0] ),
    .CLK(clknet_1_0__leaf_clk));
 sky130_fd_sc_hd__dfxtp_1 \shift_reg[1]$_SDFF_PP0_  (.D(_0_),
    .Q(\shift_reg[1] ),
    .CLK(clknet_1_0__leaf_clk));
 sky130_fd_sc_hd__dfxtp_1 \shift_reg[2]$_SDFF_PP0_  (.D(_3_),
    .Q(\shift_reg[2] ),
    .CLK(clknet_1_1__leaf_clk));
endmodule
