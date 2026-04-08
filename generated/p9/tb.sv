module tb;
  localparam WIDTH = 16;
  localparam N = 8;

  logic rst;
  logic [WIDTH-1:0] x_in;
  logic [N-1:0] h;
  logic [2*WIDTH+$clog2(N):0] y_out;

  fir_filter #(.WIDTH(WIDTH), .N(N)) uut (
    .rst(rst), .x_in(x_in), .h(h), .y_out(y_out)
  );

  integer cycle;
  initial begin
    rst = '0;
    x_in = '0;
    h = '0;
    rst = 1;
    #10;
    rst = 0;

    #1;
    $display("OBS y_out=%b", y_out);
    #10;
    $finish;
  end
endmodule
